# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock  # pyright: ignore[reportMissingImports]

from ansible_collections.ansible.mariadb.plugins.module_utils.variable import (
    convert_bool,
    get_variable,
    set_variable,
    typedvalue,
)


@pytest.mark.parametrize(
    'value,expected',
    [
        (True, 'ON'),
        (False, 'OFF'),
        (1, 'ON'),
        (0, 'OFF'),
        ('1', 'ON'),
        ('0', 'OFF'),
        ('on', 'ON'),
        ('off', 'OFF'),
        ('ON', 'ON'),
        ('OFF', 'OFF'),
        (2, 2),
        ('unchanged', 'UNCHANGED'),
    ],
)
def test_convert_bool(value, expected):
    assert convert_bool(value) == expected


@pytest.mark.parametrize(
    'value,expected',
    [
        ('3', 3),
        ('3.0', 3.0),
        ('foobar', 'foobar'),
        (3, 3),
        (3.0, 3.0),
        (True, True),
        (False, False),
    ],
)
def test_typedvalue(value, expected):
    assert typedvalue(value) == expected


def test_typedvalue_raises_type_error_for_none():
    with pytest.raises(TypeError):
        typedvalue(None)


def test_get_variable_returns_matching_value():
    cursor = MagicMock()
    cursor.fetchall.return_value = [('max_connections', '100')]

    assert get_variable(cursor, 'max_connections') == '100'
    cursor.execute.assert_called_once_with(
        "SHOW GLOBAL VARIABLES WHERE Variable_name = %s",
        ('max_connections',),
    )


@pytest.mark.parametrize('rows', [[], [('max_connections', '100'), ('max_connections', '200')]])
def test_get_variable_returns_none_without_exactly_one_match(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows

    assert get_variable(cursor, 'max_connections') is None


def test_set_variable_passes_value_as_driver_parameter():
    cursor = MagicMock()
    value = "100; SELECT 'not executed'"

    set_variable(cursor, 'max_connections', value)

    cursor.execute.assert_called_once_with('SET GLOBAL `max_connections` = %s', (value,))
