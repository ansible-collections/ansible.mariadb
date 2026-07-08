from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock

from ansible_collections.ansible.mariadb.plugins.module_utils.perf_schema import (
    ensure_perf_schema_sections_supported,
    normalize_perf_schema_item,
    normalize_perf_schema_row,
    plan_section_changes,
)


def test_normalize_perf_schema_item_for_instrument_converts_bool_values():
    normalized = normalize_perf_schema_item(
        'instruments',
        {'name': 'memory/sql/THD::transactions::mem_root', 'enabled': 'yes', 'timed': 0},
    )

    assert normalized == {
        'name': 'memory/sql/THD::transactions::mem_root',
        'enabled': True,
        'timed': False,
    }


def test_normalize_perf_schema_row_for_object_uses_canonical_keys():
    normalized = normalize_perf_schema_row(
        'objects',
        {
            'OBJECT_TYPE': 'TABLE',
            'OBJECT_SCHEMA': 'db1',
            'OBJECT_NAME': 'orders',
            'ENABLED': 'YES',
            'TIMED': 'NO',
        },
    )

    assert normalized == {
        'object_type': 'TABLE',
        'object_schema': 'db1',
        'object_name': 'orders',
        'enabled': True,
        'timed': False,
    }


def test_plan_section_changes_updates_requested_instrument_only():
    current_rows = [
        {
            'NAME': 'wait/io/table/sql/handler',
            'ENABLED': 'NO',
            'TIMED': 'NO',
        },
        {
            'NAME': 'statement/sql/select',
            'ENABLED': 'YES',
            'TIMED': 'YES',
        },
    ]

    planned = plan_section_changes(
        'instruments',
        [{'name': 'wait/io/table/sql/handler', 'enabled': True, 'timed': True}],
        current_rows,
    )

    assert planned['changed'] is True
    assert [query['display'] for query in planned['queries']] == [
        "UPDATE performance_schema.setup_instruments "
        "SET ENABLED = 'YES', TIMED = 'YES' "
        "WHERE NAME = 'wait/io/table/sql/handler'"
    ]
    assert planned['rows'] == [
        {
            'name': 'wait/io/table/sql/handler',
            'enabled': True,
            'timed': True,
        }
    ]


def test_plan_section_changes_inserts_and_deletes_actors():
    current_rows = [
        {
            'HOST': '%',
            'USER': 'old_app',
            'ROLE': '%',
            'ENABLED': 'YES',
            'HISTORY': 'YES',
        }
    ]

    planned = plan_section_changes(
        'actors',
        [
            {'user': 'old_app', 'host': '%', 'role': '%', 'state': 'absent'},
            {'user': 'new_app', 'host': '%', 'role': '%', 'enabled': True, 'history': False},
        ],
        current_rows,
    )

    assert planned['changed'] is True
    assert [query['display'] for query in planned['queries']] == [
        "DELETE FROM performance_schema.setup_actors "
        "WHERE HOST = '%' AND USER = 'old_app' AND ROLE = '%'",
        "INSERT INTO performance_schema.setup_actors (HOST, USER, ROLE, ENABLED, HISTORY) "
        "VALUES ('%', 'new_app', '%', 'YES', 'NO')",
    ]
    assert planned['rows'] == [
        {
            'user': 'new_app',
            'host': '%',
            'role': '%',
            'enabled': True,
            'history': False,
        }
    ]


def test_plan_section_changes_fails_for_missing_non_insertable_row():
    with pytest.raises(ValueError) as exc:
        plan_section_changes(
            'instruments',
            [{'name': 'statement/%', 'enabled': True, 'timed': True}],
            [],
        )

    assert str(exc.value) == (
        "Performance Schema section 'instruments' does not contain the requested row "
        "{'name': 'statement/%'}"
    )


def test_ensure_perf_schema_sections_supported_fails_when_columns_are_missing():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {'TABLE_NAME': 'setup_instruments', 'COLUMN_NAME': 'NAME'},
        {'TABLE_NAME': 'setup_instruments', 'COLUMN_NAME': 'ENABLED'},
    ]

    module = MagicMock()
    module.fail_json.side_effect = RuntimeError

    with pytest.raises(RuntimeError):
        ensure_perf_schema_sections_supported(module, cursor, ['instruments'])

    module.fail_json.assert_called_once_with(
        msg="Performance Schema section 'instruments' is not supported by the server. Missing columns: TIMED"
    )
