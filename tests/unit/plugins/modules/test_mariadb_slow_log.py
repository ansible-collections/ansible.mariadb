# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mariadb.plugins.modules.mariadb_slow_log import MySQLSlowLog, typedvalue


class FakeCursor(object):
    def __init__(self, variables):
        self.variables = variables.copy()
        self.executed = []
        self._rows = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

        if query == "SHOW GLOBAL VARIABLES WHERE Variable_name = %s":
            variable_name = params[0]
            if variable_name in self.variables:
                self._rows = [(variable_name, self.variables[variable_name])]
            else:
                self._rows = []
            return

        if query.startswith("SET GLOBAL "):
            variable_name = query.split('`')[1]
            self.variables[variable_name] = params[0]
            self._rows = []
            return

        if query == "FLUSH SLOW LOGS":
            self._rows = []
            return

        raise AssertionError('Unexpected query: %s' % query)

    def fetchall(self):
        return list(self._rows)


class ModuleStub(object):
    def fail_json(self, **kwargs):
        raise RuntimeError(kwargs['msg'])


def test_typedvalue_raises_type_error_for_none():
    with pytest.raises(TypeError):
        typedvalue(None)


@pytest.mark.parametrize('value', ['', 'invalid'])
def test_normalize_log_output_rejects_empty_and_invalid_values(value):
    slow_log = MySQLSlowLog(ModuleStub(), FakeCursor({}), 'mysql')

    with pytest.raises(RuntimeError) as exc_info:
        slow_log.normalize_log_output(value)

    assert str(exc_info.value) == 'log_output must be FILE, TABLE, NONE, or FILE,TABLE'


@pytest.mark.parametrize('value', ['NONE,FILE', 'TABLE,NONE'])
def test_normalize_log_output_rejects_none_combined_with_other_values(value):
    slow_log = MySQLSlowLog(ModuleStub(), FakeCursor({}), 'mysql')

    with pytest.raises(RuntimeError) as exc_info:
        slow_log.normalize_log_output(value)

    assert str(exc_info.value) == 'log_output cannot combine NONE with other values'


def test_read_setting_fails_when_variable_is_not_available():
    slow_log = MySQLSlowLog(ModuleStub(), FakeCursor({}), 'mysql')

    with pytest.raises(RuntimeError) as exc_info:
        slow_log.read_setting('log_output')

    assert str(exc_info.value) == 'Slow log setting "log_output" is not available on this server.'


def test_configure_returns_unchanged_when_settings_already_match():
    cursor = FakeCursor({
        'slow_query_log': 'ON',
        'long_query_time': '2.0',
        'log_output': 'FILE',
        'log_queries_not_using_indexes': 'OFF',
        'min_examined_row_limit': '100',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mysql')

    result = slow_log.configure({
        'enabled': True,
        'long_query_time': 2.0,
        'log_output': 'FILE',
        'log_queries_not_using_indexes': False,
        'min_examined_row_limit': 100,
    })

    assert result['changed'] is False
    assert result['queries'] == []
    assert result['settings'] == {
        'enabled': 'ON',
        'long_query_time': 2.0,
        'log_output': 'FILE',
        'log_queries_not_using_indexes': 'OFF',
        'min_examined_row_limit': 100,
    }


def test_configure_in_check_mode_predicts_changes_without_writes():
    cursor = FakeCursor({
        'slow_query_log': 'OFF',
        'long_query_time': '10',
        'log_output': 'TABLE',
        'log_queries_not_using_indexes': 'OFF',
        'min_examined_row_limit': '0',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mysql')

    result = slow_log.configure({
        'enabled': True,
        'log_output': 'FILE',
    }, flush=True, check_mode=True)

    assert result['changed'] is True
    assert result['queries'] == [
        "SET GLOBAL `slow_query_log` = ON",
        "SET GLOBAL `log_output` = FILE",
        "FLUSH SLOW LOGS",
    ]
    assert cursor.variables['slow_query_log'] == 'OFF'
    assert cursor.variables['log_output'] == 'TABLE'
    assert not any(query.startswith('SET GLOBAL ') for query, _params in cursor.executed)
    assert not any(query == 'FLUSH SLOW LOGS' for query, _params in cursor.executed)


def test_configure_fails_when_flush_is_requested_without_file_output():
    cursor = FakeCursor({
        'slow_query_log': 'ON',
        'long_query_time': '2',
        'log_output': 'TABLE',
        'log_queries_not_using_indexes': 'OFF',
        'min_examined_row_limit': '100',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mysql')

    with pytest.raises(RuntimeError) as exc_info:
        slow_log.configure({}, flush=True)

    assert 'flush requires FILE log_output' in str(exc_info.value)


def test_configure_uses_mariadb_aliases():
    cursor = FakeCursor({
        'log_slow_query': 'ON',
        'log_slow_query_time': '1.5',
        'log_output': 'FILE,TABLE',
        'log_queries_not_using_indexes': 'ON',
        'log_slow_min_examined_row_limit': '25',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mariadb')

    result = slow_log.configure({
        'enabled': True,
        'long_query_time': 1.5,
        'log_output': 'TABLE,FILE',
        'log_queries_not_using_indexes': True,
        'min_examined_row_limit': 25,
    })

    assert result['changed'] is False
    assert result['settings'] == {
        'enabled': 'ON',
        'long_query_time': 1.5,
        'log_output': 'FILE,TABLE',
        'log_queries_not_using_indexes': 'ON',
        'min_examined_row_limit': 25,
    }


def test_configure_appends_flush_after_setting_queries():
    cursor = FakeCursor({
        'slow_query_log': 'OFF',
        'long_query_time': '2',
        'log_output': 'FILE',
        'log_queries_not_using_indexes': 'OFF',
        'min_examined_row_limit': '100',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mysql')

    result = slow_log.configure({
        'enabled': True,
    }, flush=True)

    assert result['changed'] is True
    assert result['queries'] == [
        "SET GLOBAL `slow_query_log` = ON",
        "FLUSH SLOW LOGS",
    ]
    assert cursor.variables['slow_query_log'] == 'ON'


def test_configure_treats_string_boolean_values_as_idempotent():
    cursor = FakeCursor({
        'slow_query_log': '1',
        'long_query_time': '2',
        'log_output': 'FILE',
        'log_queries_not_using_indexes': '0',
        'min_examined_row_limit': '100',
    })

    slow_log = MySQLSlowLog(ModuleStub(), cursor, 'mysql')

    result = slow_log.configure({
        'enabled': True,
        'log_queries_not_using_indexes': False,
    })

    assert result['changed'] is False
    assert result['queries'] == []
    assert result['settings']['enabled'] == 'ON'
    assert result['settings']['log_queries_not_using_indexes'] == 'OFF'
