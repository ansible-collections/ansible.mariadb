from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from contextlib import contextmanager
import json
import sys

import pytest

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock  # pyright: ignore[reportMissingImports]

from ansible.module_utils import basic
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_bytes
try:
    from ansible.module_utils.testing import patch_module_args  # pyright: ignore[reportMissingImports]
except ImportError:
    patch_module_args = None

from ansible_collections.ansible.mariadb.plugins.modules import mariadb_perf_schema
from ansible_collections.ansible.mariadb.plugins.modules.mariadb_perf_schema import MySQLPerfSchema


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


def test_apply_in_check_mode_returns_predicted_queries_without_executing_updates():
    support_rows = [
        {'TABLE_NAME': 'setup_instruments', 'COLUMN_NAME': 'NAME'},
        {'TABLE_NAME': 'setup_instruments', 'COLUMN_NAME': 'ENABLED'},
        {'TABLE_NAME': 'setup_instruments', 'COLUMN_NAME': 'TIMED'},
    ]
    current_rows = [
        {'NAME': 'wait/io/table/sql/handler', 'ENABLED': 'NO', 'TIMED': 'NO'},
    ]

    cursor = MagicMock()

    def execute_side_effect(query, params=None):
        if query.startswith('SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS'):
            cursor.fetchall.return_value = support_rows
        elif query == 'SELECT NAME, ENABLED, TIMED FROM performance_schema.setup_instruments':
            cursor.fetchall.return_value = current_rows
        else:
            raise AssertionError('Unexpected query: %s' % query)

    cursor.execute.side_effect = execute_side_effect

    module = MagicMock()
    module.check_mode = True
    executor = MySQLPerfSchema(module, cursor)

    result = executor.apply({
        'instruments': [
            {'name': 'wait/io/table/sql/handler', 'enabled': True, 'timed': True},
        ]
    })

    assert result == {
        'changed': True,
        'queries': [
            "UPDATE performance_schema.setup_instruments "
            "SET ENABLED = 'YES', TIMED = 'YES' "
            "WHERE NAME = 'wait/io/table/sql/handler'"
        ],
        'instruments': [
            {
                'name': 'wait/io/table/sql/handler',
                'enabled': True,
                'timed': True,
            }
        ],
    }
    assert cursor.execute.call_count == 2


def test_apply_executes_mutations_and_returns_rows_for_multiple_sections():
    support_rows = [
        {'TABLE_NAME': 'setup_consumers', 'COLUMN_NAME': 'NAME'},
        {'TABLE_NAME': 'setup_consumers', 'COLUMN_NAME': 'ENABLED'},
        {'TABLE_NAME': 'setup_actors', 'COLUMN_NAME': 'HOST'},
        {'TABLE_NAME': 'setup_actors', 'COLUMN_NAME': 'USER'},
        {'TABLE_NAME': 'setup_actors', 'COLUMN_NAME': 'ROLE'},
        {'TABLE_NAME': 'setup_actors', 'COLUMN_NAME': 'ENABLED'},
        {'TABLE_NAME': 'setup_actors', 'COLUMN_NAME': 'HISTORY'},
    ]
    consumer_rows = [
        {'NAME': 'events_waits_current', 'ENABLED': 'NO'},
    ]
    actor_rows = []

    cursor = MagicMock()

    def execute_side_effect(query, params=None):
        if query.startswith('SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS'):
            cursor.fetchall.return_value = support_rows
        elif query == 'SELECT NAME, ENABLED FROM performance_schema.setup_consumers':
            cursor.fetchall.return_value = consumer_rows
        elif query == 'SELECT HOST, USER, ROLE, ENABLED, HISTORY FROM performance_schema.setup_actors':
            cursor.fetchall.return_value = actor_rows
        else:
            cursor.fetchall.return_value = []

    cursor.execute.side_effect = execute_side_effect

    module = MagicMock()
    module.check_mode = False
    executor = MySQLPerfSchema(module, cursor)

    result = executor.apply({
        'consumers': [
            {'name': 'events_waits_current', 'enabled': True},
        ],
        'actors': [
            {'user': 'app', 'host': '%', 'role': '%', 'enabled': True, 'history': False},
        ],
    })

    assert result == {
        'changed': True,
        'queries': [
            "UPDATE performance_schema.setup_consumers "
            "SET ENABLED = 'YES' "
            "WHERE NAME = 'events_waits_current'",
            "INSERT INTO performance_schema.setup_actors (HOST, USER, ROLE, ENABLED, HISTORY) "
            "VALUES ('%', 'app', '%', 'YES', 'NO')",
        ],
        'consumers': [
            {'name': 'events_waits_current', 'enabled': True},
        ],
        'actors': [
            {'user': 'app', 'host': '%', 'role': '%', 'enabled': True, 'history': False},
        ],
    }
    assert cursor.execute.call_args_list[2][0][0].startswith('UPDATE performance_schema.setup_consumers')
    assert cursor.execute.call_args_list[4][0][0].startswith('INSERT INTO performance_schema.setup_actors')


def test_get_section_rows_selects_only_key_and_value_columns():
    cursor = MagicMock()
    cursor.fetchall.return_value = []

    executor = MySQLPerfSchema(MagicMock(), cursor)

    executor.get_section_rows('objects')

    cursor.execute.assert_called_once_with(
        'SELECT OBJECT_TYPE, OBJECT_SCHEMA, OBJECT_NAME, ENABLED, TIMED FROM performance_schema.setup_objects'
    )


@pytest.mark.parametrize(
    'module_args,missing_fields',
    [
        (
            {
                'login_unix_socket': '/run/mysqld/mysqld.sock',
                'actors': [{'user': 'app', 'host': '%', 'role': '%'}],
            },
            ('enabled', 'history'),
        ),
        (
            {
                'login_unix_socket': '/run/mysqld/mysqld.sock',
                'objects': [{'object_type': 'TABLE', 'object_schema': 'app', 'object_name': 'orders'}],
            },
            ('enabled', 'timed'),
        ),
    ],
)
def test_main_validates_nested_required_fields_before_connect(monkeypatch, module_args, missing_fields):
    with set_module_args(module_args):
        monkeypatch.setattr(AnsibleModule, 'exit_json', exit_json)
        monkeypatch.setattr(AnsibleModule, 'fail_json', fail_json)
        monkeypatch.setattr(mariadb_perf_schema, 'mysql_driver', object())

        def unexpected_connect(*args, **kwargs):
            raise AssertionError('mysql_connect should not be called')

        monkeypatch.setattr(mariadb_perf_schema, 'mysql_connect', unexpected_connect)

        with pytest.raises(AnsibleFailJson) as exc:
            mariadb_perf_schema.main()

    message = exc.value.args[0]['msg']
    for field in missing_fields:
        assert field in message


def test_main_returns_prefixed_validation_error_for_invalid_perf_schema_request(monkeypatch):
    with set_module_args(
        {
            'login_unix_socket': '/run/mysqld/mysqld.sock',
            'instruments': [{'name': 'statement/sql/select', 'enabled': True, 'timed': True}],
        }
    ):
        monkeypatch.setattr(AnsibleModule, 'exit_json', exit_json)
        monkeypatch.setattr(AnsibleModule, 'fail_json', fail_json)
        monkeypatch.setattr(mariadb_perf_schema, 'mysql_driver', object())
        monkeypatch.setattr(mariadb_perf_schema, 'mysql_connect', lambda *args, **kwargs: (MagicMock(), MagicMock()))

        def invalid_request(self, params):
            raise ValueError('bad request')

        monkeypatch.setattr(mariadb_perf_schema.MySQLPerfSchema, 'apply', invalid_request)

        with pytest.raises(AnsibleFailJson) as exc:
            mariadb_perf_schema.main()

    assert exc.value.args[0]['msg'] == 'invalid performance schema request: bad request'
