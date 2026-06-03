# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mysql.plugins.module_utils.implementations.mysql.user import (
    server_supports_mysql_native_password,
    supports_identified_by_password,
)
from ..utils import dummy_cursor_class


@pytest.mark.parametrize(
    'function_return,cursor_output,cursor_ret_type',
    [
        (True, '5.5.1-mysql', 'list'),
        (True, '5.7.0-mysql', 'dict'),
        (False, '8.0.22-mysql', 'list'),
        (False, '8.1.2-mysql', 'dict'),
        (False, '9.0.0-mysql', 'list'),
        (False, '8.0.0-mysql', 'list'),
        (False, '8.0.11-mysql', 'dict'),
        (False, '8.0.21-mysql', 'list'),
    ]
)
def test_supports_identified_by_password(function_return, cursor_output, cursor_ret_type):
    """
    Tests whether 'CREATE USER %s@%s IDENTIFIED BY PASSWORD %s' is supported,
    which is currently supported by everything besides MySQL >= 8.0.
    """
    cursor = dummy_cursor_class(cursor_output, cursor_ret_type)
    assert supports_identified_by_password(cursor) == function_return


@pytest.mark.parametrize(
    'cursor_output,cursor_ret_type,function_return',
    [
        ('5.7.0-mysql', 'list', True),
        ('8.0.38-mysql', 'dict', True),
        ('8.4.9-mysql', 'list', True),
        ('9.6.0-mysql', 'dict', True),
        ('9.7.0-mysql', 'list', False),
        ('9.7.1-mysql', 'dict', False),
        ('10.0.0-mysql', 'list', False),
    ]
)
def test_server_supports_mysql_native_password(cursor_output, cursor_ret_type, function_return):
    cursor = dummy_cursor_class(cursor_output, cursor_ret_type)
    assert server_supports_mysql_native_password(cursor) == function_return
