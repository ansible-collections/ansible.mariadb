# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from contextlib import contextmanager
import importlib
import json
import sys

import pytest

from ansible.module_utils import basic
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_bytes
try:
    from ansible.module_utils.testing import patch_module_args  # pyright: ignore[reportMissingImports]
except ImportError:
    patch_module_args = None

MARIADB_REPLICATION_FILTER_MODULE = 'ansible_collections.ansible.mariadb.plugins.modules.mariadb_replication_filter'

try:
    mariadb_replication_filter_module = importlib.import_module(MARIADB_REPLICATION_FILTER_MODULE)
except ModuleNotFoundError as exc:
    if exc.name != MARIADB_REPLICATION_FILTER_MODULE:
        raise
    _IMPORT_ERROR = (
        "mariadb_replication_filter module not yet implemented - create "
        f"plugins/modules/mariadb_replication_filter.py first. Original error: {exc}"
    )
else:
    apply_filters = mariadb_replication_filter_module.apply_filters
    build_filter_query = mariadb_replication_filter_module.build_filter_query
    get_filter_values = mariadb_replication_filter_module.get_filter_values
    normalize_filter_values = mariadb_replication_filter_module.normalize_filter_values
    normalize_filter_variables = mariadb_replication_filter_module.normalize_filter_variables
    plan_filter_changes = mariadb_replication_filter_module.plan_filter_changes
    supports_connection_name = mariadb_replication_filter_module.supports_connection_name
    _IMPORT_ERROR = None


class AnsibleExitJson(Exception):
    pass


class AnsibleFailJson(Exception):
    pass


def exit_json(*args, **kwargs):
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    kwargs['failed'] = True
    raise AnsibleFailJson(kwargs)


@contextmanager
def set_module_args(args):
    module_args = dict(args)
    original_argv = sys.argv[:]
    sys.argv = ['ansible_unittest']

    try:
        if patch_module_args is not None:
            with patch_module_args(module_args):
                yield
            return

        original_args = getattr(basic, '_ANSIBLE_ARGS', None)
        original_profile = getattr(basic, '_ANSIBLE_PROFILE', None)
        had_profile = hasattr(basic, '_ANSIBLE_PROFILE')

        basic._ANSIBLE_ARGS = to_bytes(json.dumps({'ANSIBLE_MODULE_ARGS': module_args}))
        basic._ANSIBLE_PROFILE = 'legacy'

        try:
            yield
        finally:
            basic._ANSIBLE_ARGS = original_args
            if had_profile:
                basic._ANSIBLE_PROFILE = original_profile
            else:
                delattr(basic, '_ANSIBLE_PROFILE')
    finally:
        sys.argv = original_argv


def _require_module():
    if _IMPORT_ERROR:
        pytest.fail(_IMPORT_ERROR)


class FakeCursor(object):
    def __init__(self, version='10.4.0-mariadb', variables=None, connection_variables=None):
        self.version = version
        self.variables = dict(variables or {})
        self.connection_variables = dict(connection_variables or {})
        self.default_master_connection = ''
        self.executed = []
        self._rows = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

        if query == 'SELECT VERSION() AS version':
            self._rows = [{'version': self.version}]
            return

        if query == 'SHOW GLOBAL VARIABLES WHERE Variable_name = %s':
            variable_name = params[0]
            active_variables = self.variables
            if self.default_master_connection:
                active_variables = self.connection_variables.get(self.default_master_connection, {})
            if variable_name in active_variables:
                self._rows = [(variable_name, active_variables[variable_name])]
            else:
                self._rows = []
            return

        if query.startswith('SELECT @@GLOBAL.') and query.endswith(' AS Value'):
            variable_name = query[len('SELECT @@GLOBAL.'): -len(' AS Value')]
            active_variables = self.variables
            if self.default_master_connection:
                active_variables = self.connection_variables.get(self.default_master_connection, {})
            self._rows = [{'Value': active_variables.get(variable_name, '')}]
            return

        if (
            query.startswith("SHOW REPLICA '") or query.startswith("SHOW SLAVE '")
        ) and query.endswith("' STATUS"):
            prefix = "SHOW REPLICA '" if query.startswith("SHOW REPLICA '") else "SHOW SLAVE '"
            connection_name = query[len(prefix): -len("' STATUS")]
            active_variables = self.connection_variables.get(connection_name, {})
            self._rows = [{
                'Replicate_Do_DB': active_variables.get('replicate_do_db', ''),
                'Replicate_Ignore_DB': active_variables.get('replicate_ignore_db', ''),
                'Replicate_Do_Table': active_variables.get('replicate_do_table', ''),
                'Replicate_Ignore_Table': active_variables.get('replicate_ignore_table', ''),
                'Replicate_Wild_Do_Table': active_variables.get('replicate_wild_do_table', ''),
                'Replicate_Wild_Ignore_Table': active_variables.get('replicate_wild_ignore_table', ''),
            }]
            return

        if query == 'SET @@default_master_connection = %s':
            self.default_master_connection = params[0]
            self._rows = []
            return

        if query.startswith('SET GLOBAL '):
            variable_name = query.split('`')[1]
            active_variables = self.variables
            if self.default_master_connection:
                active_variables = self.connection_variables.setdefault(self.default_master_connection, {})
            active_variables[variable_name] = params[0]
            self._rows = []
            return

        raise AssertionError(f'Unexpected query: {query} (params={params})')

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class ModuleStub(object):
    def __init__(self, check_mode=False):
        self.check_mode = check_mode

    def fail_json(self, **kwargs):
        raise RuntimeError(kwargs.get('msg', 'fail_json called'))


class CursorStub(object):
    def __init__(self, responses=None, version='10.11.0-MariaDB'):
        self.responses = list(responses or [])
        self.version = version
        self.executed = []
        self._version_requested = False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query == 'SELECT VERSION() AS version':
            self._version_requested = True

    def fetchone(self):
        if self._version_requested:
            self._version_requested = False
            return {'version': self.version}
        if self.responses:
            rows = self.responses.pop(0)
            return rows[0] if rows else None
        return None

    def fetchall(self):
        if self.responses:
            return self.responses.pop(0)
        return []


def test_module_is_importable():
    _require_module()


def test_normalize_filter_values_orders_and_deduplicates_items():
    _require_module()

    assert normalize_filter_values([' reporting ', 'analytics', 'reporting']) == [
        'analytics',
        'reporting',
    ]


def test_normalize_filter_variables_maps_csv_rules():
    _require_module()

    variables = {
        'replicate_do_db': 'app,reporting',
        'replicate_ignore_db': '',
        'replicate_do_table': 'app.orders,reporting.summary',
        'replicate_ignore_table': '',
        'replicate_wild_do_table': 'app.%,reporting.sales_%',
        'replicate_wild_ignore_table': '',
    }

    assert normalize_filter_variables(variables) == {
        'replicate_do_db': ['app', 'reporting'],
        'replicate_ignore_db': [],
        'replicate_do_table': ['app.orders', 'reporting.summary'],
        'replicate_ignore_table': [],
        'replicate_wild_do_table': ['app.%', 'reporting.sales_%'],
        'replicate_wild_ignore_table': [],
    }


def test_plan_filter_changes_updates_only_requested_filters():
    _require_module()

    current_filters = {
        'replicate_do_db': ['app'],
        'replicate_ignore_db': ['archive'],
        'replicate_do_table': [],
        'replicate_ignore_table': [],
        'replicate_wild_do_table': [],
        'replicate_wild_ignore_table': [],
    }

    planned = plan_filter_changes(
        {
            'replicate_do_db': None,
            'replicate_ignore_db': ['reporting', 'analytics'],
        },
        current_filters,
        lambda param, values: {
            'sql': param,
            'params': tuple(values),
            'display': f"{param}={','.join(values)}",
        },
    )

    assert planned['changed'] is True
    assert planned['queries'] == [
        {
            'sql': 'replicate_ignore_db',
            'params': ('analytics', 'reporting'),
            'display': 'replicate_ignore_db=analytics,reporting',
        }
    ]
    assert planned['filters'] == {
        'replicate_do_db': ['app'],
        'replicate_ignore_db': ['analytics', 'reporting'],
        'replicate_do_table': [],
        'replicate_ignore_table': [],
        'replicate_wild_do_table': [],
        'replicate_wild_ignore_table': [],
    }


def test_plan_filter_changes_treats_order_only_difference_as_idempotent():
    _require_module()

    planned = plan_filter_changes(
        {'replicate_ignore_db': ['reporting', 'analytics']},
        {
            'replicate_do_db': [],
            'replicate_ignore_db': ['analytics', 'reporting'],
            'replicate_do_table': [],
            'replicate_ignore_table': [],
            'replicate_wild_do_table': [],
            'replicate_wild_ignore_table': [],
        },
        lambda param, values: {'sql': param, 'params': tuple(values), 'display': param},
    )

    assert planned['changed'] is False
    assert planned['queries'] == []


def test_build_filter_query_uses_csv_values_and_clear():
    _require_module()

    assert build_filter_query('replicate_do_db', ['reporting', 'analytics']) == {
        'sql': "SET GLOBAL `replicate_do_db` = %s",
        'params': ('analytics,reporting',),
        'display': "SET GLOBAL `replicate_do_db` = 'analytics,reporting'",
    }

    assert build_filter_query('replicate_do_db', []) == {
        'sql': "SET GLOBAL `replicate_do_db` = %s",
        'params': ('',),
        'display': "SET GLOBAL `replicate_do_db` = ''",
    }


def test_supports_connection_name_checks_version_threshold():
    _require_module()

    assert supports_connection_name('10.0.0-MariaDB') is False
    assert supports_connection_name('10.0.1-MariaDB') is True


def test_get_filter_values_uses_connection_status_context():
    _require_module()

    cursor = CursorStub([[
        {
            'Replicate_Do_DB': 'app,reporting',
            'Replicate_Ignore_DB': '',
            'Replicate_Do_Table': 'app.orders',
            'Replicate_Ignore_Table': '',
            'Replicate_Wild_Do_Table': 'reporting.sales_%',
            'Replicate_Wild_Ignore_Table': '',
        }
    ]])

    assert get_filter_values(
        ModuleStub(),
        cursor,
        '10.11.0-MariaDB',
        connection_name=r'analytics\path',
    ) == {
        'replicate_do_db': 'app,reporting',
        'replicate_ignore_db': '',
        'replicate_do_table': 'app.orders',
        'replicate_ignore_table': '',
        'replicate_wild_do_table': 'reporting.sales_%',
        'replicate_wild_ignore_table': '',
    }
    assert cursor.executed == [
        (r"SHOW REPLICA 'analytics\\path' STATUS", None),
    ]


def test_get_filter_values_uses_legacy_slave_status_context():
    _require_module()

    cursor = CursorStub([[
        {
            'Replicate_Do_DB': 'app,reporting',
            'Replicate_Ignore_DB': '',
            'Replicate_Do_Table': 'app.orders',
            'Replicate_Ignore_Table': '',
            'Replicate_Wild_Do_Table': 'reporting.sales_%',
            'Replicate_Wild_Ignore_Table': '',
        }
    ]])

    assert get_filter_values(
        ModuleStub(),
        cursor,
        '10.0.1-MariaDB',
        connection_name='analytics',
    ) == {
        'replicate_do_db': 'app,reporting',
        'replicate_ignore_db': '',
        'replicate_do_table': 'app.orders',
        'replicate_ignore_table': '',
        'replicate_wild_do_table': 'reporting.sales_%',
        'replicate_wild_ignore_table': '',
    }
    assert cursor.executed == [
        ("SHOW SLAVE 'analytics' STATUS", None),
    ]


def test_get_filter_values_reads_global_variables_without_connection_name():
    _require_module()

    cursor = CursorStub([
        [('app,reporting',)],
        [('',)],
        [('app.orders',)],
        [('',)],
        [('reporting.sales_%',)],
        [('',)],
    ])

    assert get_filter_values(ModuleStub(), cursor, '10.11.0-MariaDB') == {
        'replicate_do_db': 'app,reporting',
        'replicate_ignore_db': '',
        'replicate_do_table': 'app.orders',
        'replicate_ignore_table': '',
        'replicate_wild_do_table': 'reporting.sales_%',
        'replicate_wild_ignore_table': '',
    }
    assert cursor.executed == [
        ('SELECT @@GLOBAL.replicate_do_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_ignore_table AS Value', None),
    ]


def test_get_filter_values_rejects_connection_name_on_old_versions():
    _require_module()

    with pytest.raises(RuntimeError) as exc_info:
        get_filter_values(ModuleStub(), CursorStub(), '10.0.0-MariaDB', connection_name='analytics')

    assert str(exc_info.value) == 'connection_name requires MariaDB 10.0.1 or newer'


def test_apply_filters_executes_change_query_in_real_mode():
    _require_module()

    cursor = FakeCursor()

    result = apply_filters(
        ModuleStub(check_mode=False), cursor, '10.11.0-MariaDB', {'replicate_do_db': ['app']}
    )

    assert result == {
        'changed': True,
        'queries': [
            "SET GLOBAL `replicate_do_db` = 'app'",
        ],
        'filters': {
            'replicate_do_db': ['app'],
            'replicate_ignore_db': [],
            'replicate_do_table': [],
            'replicate_ignore_table': [],
            'replicate_wild_do_table': [],
            'replicate_wild_ignore_table': [],
        },
    }
    assert cursor.executed == [
        ('SELECT @@GLOBAL.replicate_do_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_ignore_table AS Value', None),
        ('SET GLOBAL `replicate_do_db` = %s', ('app',)),
    ]
    assert cursor.variables['replicate_do_db'] == 'app'


def test_apply_filters_returns_unchanged_when_filter_matches_different_order():
    _require_module()

    cursor = FakeCursor(variables={'replicate_ignore_db': 'analytics,reporting'})

    result = apply_filters(
        ModuleStub(check_mode=False), cursor, '10.11.0-MariaDB', {'replicate_ignore_db': ['reporting', 'analytics']}
    )

    assert result['changed'] is False
    assert result['queries'] == []
    assert cursor.executed == [
        ('SELECT @@GLOBAL.replicate_do_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_db AS Value', None),
        ('SELECT @@GLOBAL.replicate_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_ignore_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_do_table AS Value', None),
        ('SELECT @@GLOBAL.replicate_wild_ignore_table AS Value', None),
    ]


def test_apply_rejects_filter_values_containing_commas():
    _require_module()

    with pytest.raises(RuntimeError) as exc_info:
        apply_filters(
            ModuleStub(check_mode=False), FakeCursor(), '10.11.0-MariaDB', {'replicate_do_db': ['bad,name']}
        )

    assert str(exc_info.value) == 'replication filter values cannot contain commas: bad,name'


def test_apply_rejects_invalid_table_filter_value():
    _require_module()

    with pytest.raises(RuntimeError) as exc_info:
        apply_filters(
            ModuleStub(check_mode=False), FakeCursor(), '10.11.0-MariaDB', {'replicate_do_table': ['missing_separator']}
        )

    assert str(exc_info.value) == 'replicate_do_table values must use database.table syntax: missing_separator'


@pytest.mark.parametrize('param', ('replicate_wild_do_table', 'replicate_wild_ignore_table'))
def test_apply_rejects_invalid_wildcard_filter_value(param):
    _require_module()

    with pytest.raises(RuntimeError) as exc_info:
        apply_filters(ModuleStub(check_mode=False), FakeCursor(), '10.11.0-MariaDB', {param: ['missing_separator']})

    assert str(exc_info.value) == f'{param} values must use database.table syntax: missing_separator'


def test_apply_filters_check_mode_predicts_changes_without_writes():
    _require_module()

    cursor = FakeCursor(
        version='10.11.0-MariaDB',
        connection_variables={
            'analytics': {
                'replicate_do_db': 'archive',
                'replicate_ignore_db': '',
                'replicate_do_table': '',
                'replicate_ignore_table': '',
                'replicate_wild_do_table': '',
                'replicate_wild_ignore_table': '',
            }
        },
    )

    result = apply_filters(
        ModuleStub(check_mode=True), cursor, '10.11.0-MariaDB',
        {'replicate_do_db': ['reporting', 'app']},
        connection_name='analytics',
    )

    assert result == {
        'changed': True,
        'queries': [
            "SET GLOBAL `replicate_do_db` = 'app,reporting'",
        ],
        'filters': {
            'replicate_do_db': ['app', 'reporting'],
            'replicate_ignore_db': [],
            'replicate_do_table': [],
            'replicate_ignore_table': [],
            'replicate_wild_do_table': [],
            'replicate_wild_ignore_table': [],
        },
    }
    assert cursor.executed == [
        ("SHOW REPLICA 'analytics' STATUS", None),
    ]
    assert cursor.connection_variables['analytics']['replicate_do_db'] == 'archive'


def test_apply_filters_executes_queries_with_connection_context():
    _require_module()

    cursor = FakeCursor(
        version='10.11.0-MariaDB',
        connection_variables={
            'analytics': {
                'replicate_do_db': '',
                'replicate_ignore_db': '',
                'replicate_do_table': '',
                'replicate_ignore_table': '',
                'replicate_wild_do_table': '',
                'replicate_wild_ignore_table': '',
            }
        },
    )

    result = apply_filters(
        ModuleStub(check_mode=False), cursor, '10.11.0-MariaDB',
        {'replicate_ignore_db': ['archive', 'analytics']},
        connection_name='analytics',
    )

    assert result == {
        'changed': True,
        'queries': [
            "SET GLOBAL `replicate_ignore_db` = 'analytics,archive'",
        ],
        'filters': {
            'replicate_do_db': [],
            'replicate_ignore_db': ['analytics', 'archive'],
            'replicate_do_table': [],
            'replicate_ignore_table': [],
            'replicate_wild_do_table': [],
            'replicate_wild_ignore_table': [],
        },
    }
    assert cursor.connection_variables['analytics']['replicate_ignore_db'] == 'analytics,archive'
    assert cursor.executed == [
        ("SHOW REPLICA 'analytics' STATUS", None),
        ('SET @@default_master_connection = %s', ('analytics',)),
        ('SET GLOBAL `replicate_ignore_db` = %s', ('analytics,archive',)),
        ('SET @@default_master_connection = %s', ('',)),
    ]


def test_main_requires_at_least_one_filter_before_connect(monkeypatch):
    _require_module()

    with set_module_args({'login_unix_socket': '/run/mysqld/mysqld.sock'}):
        monkeypatch.setattr(AnsibleModule, 'exit_json', exit_json)
        monkeypatch.setattr(AnsibleModule, 'fail_json', fail_json)
        monkeypatch.setattr(mariadb_replication_filter_module, 'driver', object())

        def unexpected_connect(*args, **kwargs):
            raise AssertionError('connect should not be called')

        monkeypatch.setattr(mariadb_replication_filter_module, 'connect', unexpected_connect)

        with pytest.raises(AnsibleFailJson) as exc:
            mariadb_replication_filter_module.main()

    assert exc.value.args[0]['msg'] == 'at least one replication filter option must be provided'
