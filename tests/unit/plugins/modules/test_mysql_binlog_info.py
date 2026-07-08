# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock

from ansible_collections.ansible.mariadb.plugins.modules.mariadb_binlog_info import MySQL_Binlog_Info


def test_get_info_returns_requested_subsets_with_normalized_totals():
    query_results = {
        "SHOW GLOBAL VARIABLES LIKE 'log_bin'": [
            {'Variable_name': 'log_bin', 'Value': 'ON'}
        ],
        'SHOW BINARY LOG STATUS': [
            {'File': 'binlog.000003', 'Position': '456', 'Executed_Gtid_Set': 'uuid:1-9'}
        ],
        'SHOW BINARY LOGS': [
            {'Log_name': 'binlog.000001', 'File_size': '123', 'Encrypted': 'No'},
            {'Log_name': 'binlog.000002', 'File_size': '456', 'Encrypted': 'Yes'},
        ],
    }

    cursor = MagicMock()

    def execute_side_effect(query):
        cursor.fetchall.return_value = query_results[query]

    cursor.execute.side_effect = execute_side_effect

    info = MySQL_Binlog_Info(MagicMock(), cursor, 'mysql', '8.4.9')

    result = info.get_info(['current', 'logs', 'totals'])

    assert result == {
        'current': {
            'file': 'binlog.000003',
            'position': 456,
            'executed_gtid_set': 'uuid:1-9',
        },
        'logs': [
            {'name': 'binlog.000001', 'size': 123, 'encrypted': 'No'},
            {'name': 'binlog.000002', 'size': 456, 'encrypted': 'Yes'},
        ],
        'totals': {
            'count': 2,
            'size': 579,
        },
    }


def test_get_info_settings_returns_only_binlog_related_variables():
    cursor = MagicMock()
    query_results = {
        "SHOW GLOBAL VARIABLES LIKE 'log_bin'": [
            {'Variable_name': 'log_bin', 'Value': 'ON'},
        ],
        'SHOW GLOBAL VARIABLES': [
            {'Variable_name': 'log_bin', 'Value': 'ON'},
            {'Variable_name': 'binlog_format', 'Value': 'ROW'},
            {'Variable_name': 'max_binlog_size', 'Value': '1048576'},
            {'Variable_name': 'sync_binlog', 'Value': '1'},
            {'Variable_name': 'version', 'Value': '8.4.9'},
        ],
    }

    def execute_side_effect(query):
        cursor.fetchall.return_value = query_results[query]

    cursor.execute.side_effect = execute_side_effect

    info = MySQL_Binlog_Info(MagicMock(), cursor, 'mysql', '8.4.9')

    result = info.get_info(['settings'])

    assert cursor.execute.call_args_list[0][0] == ("SHOW GLOBAL VARIABLES LIKE 'log_bin'",)
    assert cursor.execute.call_args_list[1][0] == ('SHOW GLOBAL VARIABLES',)
    assert result == {
        'settings': {
            'log_bin': 'ON',
            'binlog_format': 'ROW',
            'max_binlog_size': 1048576,
            'sync_binlog': 1,
        },
    }


def test_get_info_uses_mariadb_gtid_fallback_when_missing_from_status():
    query_results = {
        "SHOW GLOBAL VARIABLES LIKE 'log_bin'": [
            {'Variable_name': 'log_bin', 'Value': 'ON'}
        ],
        'SHOW BINLOG STATUS': [
            {'File': 'mariadb-bin.000001', 'Position': '789'}
        ],
        'SELECT @@global.gtid_binlog_pos AS gtid_binlog_pos': [
            {'gtid_binlog_pos': '0-1-2'}
        ],
    }

    cursor = MagicMock()

    def execute_side_effect(query):
        cursor.fetchall.return_value = query_results[query]

    cursor.execute.side_effect = execute_side_effect

    info = MySQL_Binlog_Info(MagicMock(), cursor, 'mariadb', '10.11.8')

    result = info.get_info(['current'])

    assert result == {
        'current': {
            'file': 'mariadb-bin.000001',
            'position': 789,
            'executed_gtid_set': '0-1-2',
        },
    }


def test_get_info_exclusion_filter_omits_requested_subset():
    query_results = {
        "SHOW GLOBAL VARIABLES LIKE 'log_bin'": [
            {'Variable_name': 'log_bin', 'Value': 'ON'}
        ],
        'SHOW BINARY LOG STATUS': [
            {'File': 'binlog.000003', 'Position': '456', 'Executed_Gtid_Set': 'uuid:1-9'}
        ],
        'SHOW BINARY LOGS': [
            {'Log_name': 'binlog.000001', 'File_size': '123', 'Encrypted': 'No'},
        ],
    }

    cursor = MagicMock()

    def execute_side_effect(query):
        cursor.fetchall.return_value = query_results[query]

    cursor.execute.side_effect = execute_side_effect

    info = MySQL_Binlog_Info(MagicMock(), cursor, 'mysql', '8.4.9')

    result = info.get_info(['!settings'])

    assert result == {
        'current': {
            'file': 'binlog.000003',
            'position': 456,
            'executed_gtid_set': 'uuid:1-9',
        },
        'logs': [
            {'name': 'binlog.000001', 'size': 123, 'encrypted': 'No'},
        ],
        'totals': {
            'count': 1,
            'size': 123,
        },
    }


def test_get_info_fails_when_binary_logging_is_disabled():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {'Variable_name': 'log_bin', 'Value': 'OFF'},
    ]

    module = MagicMock()
    module.fail_json.side_effect = RuntimeError

    info = MySQL_Binlog_Info(module, cursor, 'mysql', '8.4.9')

    with pytest.raises(RuntimeError):
        info.get_info(['settings'])

    module.fail_json.assert_called_once_with(
        msg='Binary logging is disabled (log_bin=OFF), mysql_binlog_info cannot be used.'
    )
