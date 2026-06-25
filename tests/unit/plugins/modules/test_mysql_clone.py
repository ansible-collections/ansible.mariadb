# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mysql.plugins.modules.mysql_clone import (
    build_clone_query,
    ensure_clone_not_running,
    ensure_clone_plugin_active,
    get_redacted_query,
    is_terminal_state,
    main,
    should_wait_after_execute_error,
    validate_donor_allowed,
    validate_clone_support,
    wait_for_clone_completion,
)


class DummyModule(object):
    def __init__(self):
        self.msg = None
        self.params = {
            'wait_timeout': 30,
            'poll_interval': 0,
        }
        self.check_mode = False

    def fail_json(self, msg=None, **kwargs):
        self.msg = msg
        raise RuntimeError(msg)

    def exit_json(self, **kwargs):
        raise SystemExit(kwargs)


class DummyCursor(object):
    def __init__(self, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def close(self):
        return None


class DummyConnection(object):
    def close(self):
        return None


class FailingCloneCursor(DummyCursor):
    def __init__(self, error_message):
        super(FailingCloneCursor, self).__init__()
        self.error_message = error_message

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.startswith('CLONE INSTANCE FROM'):
            raise RuntimeError(self.error_message)


def assert_wait_not_called(*args, **kwargs):
    raise AssertionError('wait should not be called')


def assert_connect_not_called(_module):
    raise AssertionError('connect should not be called')


@pytest.mark.parametrize(
    'server_implementation,server_version,error_message',
    [
        ('mariadb', '11.8.7', 'MariaDB is not supported by mysql_clone.'),
        ('mysql', '8.0.16', 'mysql_clone requires MySQL 8.0.17 or newer.'),
    ]
)
def test_validate_clone_support_fails_for_unsupported_server(server_implementation, server_version, error_message):
    module = DummyModule()

    with pytest.raises(RuntimeError) as exc:
        validate_clone_support(module, server_implementation, server_version)

    assert str(exc.value) == error_message
    assert module.msg == error_message


def test_validate_clone_support_accepts_supported_mysql():
    module = DummyModule()

    validate_clone_support(module, 'mysql', '8.0.17')


@pytest.mark.parametrize(
    'require_ssl,expected_suffix',
    [
        (True, ' REQUIRE SSL'),
        (False, ' REQUIRE NO SSL'),
        (None, ''),
    ]
)
def test_build_clone_query_returns_expected_sql_and_params(require_ssl, expected_suffix):
    query, params = build_clone_query(
        donor_host='192.0.2.10',
        donor_port=3307,
        donor_user='clone_user',
        donor_password='secret',
        require_ssl=require_ssl,
    )

    assert query == 'CLONE INSTANCE FROM %s@%s:%s IDENTIFIED BY %s' + expected_suffix
    assert params == ('clone_user', '192.0.2.10', 3307, 'secret')


def test_get_redacted_query_masks_password():
    query, params = build_clone_query(
        donor_host='192.0.2.10',
        donor_port=3307,
        donor_user='clone_user',
        donor_password='secret',
    )

    assert get_redacted_query(query, params) == (
        "CLONE INSTANCE FROM 'clone_user'@'192.0.2.10':3307 IDENTIFIED BY '********'"
    )


@pytest.mark.parametrize(
    'state,output',
    [
        ('Completed', True),
        ('Failed', True),
        ('In Progress', False),
        ('Not Started', False),
        (None, False),
    ]
)
def test_is_terminal_state(state, output):
    assert is_terminal_state(state) is output


@pytest.mark.parametrize(
    'error_message,output',
    [
        ("(3707, 'Restart server failed (mysqld is not managed by supervisor process).')", True),
        ("(1045, 'Access denied for user')", False),
        ('syntax error near CLONE', False),
        (None, False),
    ]
)
def test_should_wait_after_execute_error(error_message, output):
    assert should_wait_after_execute_error(error_message) is output


def test_ensure_clone_plugin_active_fails_when_plugin_missing():
    module = DummyModule()
    cursor = DummyCursor(fetchone_results=[None])

    with pytest.raises(RuntimeError) as exc:
        ensure_clone_plugin_active(module, cursor)

    assert str(exc.value) == 'MySQL Clone plugin is not active on the recipient server.'


def test_ensure_clone_plugin_active_accepts_active_plugin():
    module = DummyModule()
    cursor = DummyCursor(fetchone_results=[{'plugin_status': 'ACTIVE'}])

    ensure_clone_plugin_active(module, cursor)


def test_validate_donor_allowed_accepts_matching_host_and_port():
    module = DummyModule()
    cursor = DummyCursor(fetchall_results=[[{'Value': '192.0.2.10:3307,198.51.100.20:3306'}]])

    validate_donor_allowed(module, cursor, '192.0.2.10', 3307)


def test_validate_donor_allowed_fails_when_donor_missing():
    module = DummyModule()
    cursor = DummyCursor(fetchall_results=[[{'Value': '198.51.100.20:3306'}]])

    with pytest.raises(RuntimeError) as exc:
        validate_donor_allowed(module, cursor, '192.0.2.10', 3307)

    assert str(exc.value) == 'Recipient clone_valid_donor_list must contain 192.0.2.10:3307.'


@pytest.mark.parametrize(
    'rows,error_message',
    [
        ([], 'clone_valid_donor_list is not available on the recipient server.'),
        ([{'Value': ''}], 'Recipient clone_valid_donor_list must contain 192.0.2.10:3307.'),
    ]
)
def test_validate_donor_allowed_handles_missing_or_empty_allow_list(rows, error_message):
    module = DummyModule()
    cursor = DummyCursor(fetchall_results=[rows])

    with pytest.raises(RuntimeError) as exc:
        validate_donor_allowed(module, cursor, '192.0.2.10', 3307)

    assert str(exc.value) == error_message


def test_ensure_clone_not_running_fails_for_in_progress_clone():
    module = DummyModule()

    with pytest.raises(RuntimeError) as exc:
        ensure_clone_not_running(module, {'STATE': 'In Progress'})

    assert str(exc.value) == 'A clone operation is already in progress on the recipient server.'


def test_wait_for_clone_completion_handles_reconnects(monkeypatch):
    module = DummyModule()
    reconnect_cursor = DummyCursor(
        fetchall_results=[
            [{'STATE': 'In Progress'}],
            [],
            [{'STATE': 'Completed', 'ERROR_MESSAGE': ''}],
            [{'STAGE': 'FILE COPY', 'STATE': 'Completed'}],
        ]
    )
    connection = DummyConnection()
    connect_results = iter([
        RuntimeError('connection lost'),
        (reconnect_cursor, connection),
        (reconnect_cursor, connection),
    ])
    time_values = iter([0, 1, 2, 3])

    def fake_connect(_module):
        result = next(connect_results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone._connect',
        fake_connect,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.time.sleep',
        lambda _: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.time.time',
        lambda: next(time_values),
    )

    status, progress = wait_for_clone_completion(module)

    assert status['STATE'] == 'Completed'
    assert progress == [{'STAGE': 'FILE COPY', 'STATE': 'Completed'}]


def test_main_returns_predictive_result_in_check_mode(monkeypatch):
    module = DummyModule()
    module.check_mode = True
    module.params.update({
        'login_user': 'root',
        'login_password': 'secret',
        'config_file': '~/.my.cnf',
        'client_cert': None,
        'client_key': None,
        'ca_cert': None,
        'check_hostname': None,
        'connect_timeout': 30,
        'wait_timeout': 30,
        'poll_interval': 5,
        'donor_host': '192.0.2.10',
        'donor_port': 3307,
        'donor_user': 'clone_user',
        'donor_password': 'supersecret',
        'require_ssl': True,
    })
    cursor = DummyCursor()
    connection = DummyConnection()

    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.AnsibleModule',
        lambda **kwargs: module,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.mysql_driver',
        object(),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone._connect',
        lambda _module: (cursor, connection),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_implementation',
        lambda _cursor: 'mysql',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_version',
        lambda _cursor: '8.0.17',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_plugin_active',
        lambda _module, _cursor: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.validate_donor_allowed',
        lambda _module, _cursor, _host, _port: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_not_running',
        lambda _module, _status: None,
    )

    with pytest.raises(SystemExit) as exc:
        main()

    result = exc.value.args[0]
    assert result['changed'] is True
    assert result['msg'] == 'Clone would be started.'
    assert result['query'] == (
        "CLONE INSTANCE FROM 'clone_user'@'192.0.2.10':3307 IDENTIFIED BY '********' REQUIRE SSL"
    )


def test_main_rejects_port_zero(monkeypatch):
    module = DummyModule()
    module.params.update({
        'login_user': 'root',
        'login_password': 'secret',
        'config_file': '~/.my.cnf',
        'client_cert': None,
        'client_key': None,
        'ca_cert': None,
        'check_hostname': None,
        'connect_timeout': 30,
        'wait_timeout': 30,
        'poll_interval': 5,
        'donor_host': '192.0.2.10',
        'donor_port': 0,
        'donor_user': 'clone_user',
        'donor_password': 'supersecret',
        'require_ssl': None,
    })

    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.AnsibleModule',
        lambda **kwargs: module,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.mysql_driver',
        object(),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone._connect',
        assert_connect_not_called,
    )

    with pytest.raises(RuntimeError) as exc:
        main()

    assert str(exc.value) == 'donor_port must be a valid unix port number (1-65535)'


def test_main_fails_immediately_for_fatal_execute_error(monkeypatch):
    module = DummyModule()
    module.params.update({
        'login_user': 'root',
        'login_password': 'secret',
        'config_file': '~/.my.cnf',
        'client_cert': None,
        'client_key': None,
        'ca_cert': None,
        'check_hostname': None,
        'connect_timeout': 30,
        'wait_timeout': 30,
        'poll_interval': 5,
        'donor_host': '192.0.2.10',
        'donor_port': 3307,
        'donor_user': 'clone_user',
        'donor_password': 'supersecret',
        'require_ssl': None,
    })
    cursor = FailingCloneCursor("(1045, 'Access denied for user')")
    connection = DummyConnection()

    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.AnsibleModule',
        lambda **kwargs: module,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.mysql_driver',
        object(),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone._connect',
        lambda _module: (cursor, connection),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_implementation',
        lambda _cursor: 'mysql',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_version',
        lambda _cursor: '8.0.17',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_plugin_active',
        lambda _module, _cursor: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.validate_donor_allowed',
        lambda _module, _cursor, _host, _port: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_not_running',
        lambda _module, _status: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.wait_for_clone_completion',
        assert_wait_not_called,
    )

    with pytest.raises(RuntimeError) as exc:
        main()

    assert str(exc.value) == "Clone failed to start. (1045, 'Access denied for user')"


def test_main_waits_after_expected_restart_error(monkeypatch):
    module = DummyModule()
    module.params.update({
        'login_user': 'root',
        'login_password': 'secret',
        'config_file': '~/.my.cnf',
        'client_cert': None,
        'client_key': None,
        'ca_cert': None,
        'check_hostname': None,
        'connect_timeout': 30,
        'wait_timeout': 30,
        'poll_interval': 5,
        'donor_host': '192.0.2.10',
        'donor_port': 3307,
        'donor_user': 'clone_user',
        'donor_password': 'supersecret',
        'require_ssl': None,
    })
    cursor = FailingCloneCursor("(3707, 'Restart server failed (mysqld is not managed by supervisor process).')")
    connection = DummyConnection()

    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.AnsibleModule',
        lambda **kwargs: module,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.mysql_driver',
        object(),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone._connect',
        lambda _module: (cursor, connection),
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_implementation',
        lambda _cursor: 'mysql',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.get_server_version',
        lambda _cursor: '8.0.17',
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_plugin_active',
        lambda _module, _cursor: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.validate_donor_allowed',
        lambda _module, _cursor, _host, _port: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.ensure_clone_not_running',
        lambda _module, _status: None,
    )
    monkeypatch.setattr(
        'ansible_collections.ansible.mysql.plugins.modules.mysql_clone.wait_for_clone_completion',
        lambda *_args, **_kwargs: ({'STATE': 'Completed'}, [{'STAGE': 'RESTART', 'STATE': 'Completed'}]),
    )

    with pytest.raises(SystemExit) as exc:
        main()

    result = exc.value.args[0]
    assert result['changed'] is True
    assert result['msg'] == 'Clone completed successfully.'
