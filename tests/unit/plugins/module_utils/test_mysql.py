from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import pytest

from ansible_collections.ansible.mariadb.plugins.module_utils.mysql import get_server_version, get_server_implementation
from ..utils import dummy_cursor_class


@pytest.mark.parametrize(
    'cursor_return_version,cursor_return_type',
    [
        ('5.7.0-mysql', 'dict'),
        ('8.0.0-mysql', 'list'),
        ('10.5.0-mariadb', 'dict'),
        ('10.5.1-mariadb', 'list'),
    ]
)
def test_get_server_version(cursor_return_version, cursor_return_type):
    """
    Test that server versions are handled properly by get_server_version() whether they're returned as a list or dict.
    """
    cursor = dummy_cursor_class(cursor_return_version, cursor_return_type)
    assert get_server_version(cursor) == cursor_return_version


@pytest.mark.parametrize(
    'cursor_return_version,cursor_return_type,server_implementation',
    [
        ('5.7.0-mysql', 'dict', 'mysql'),
        ('8.0.0-mysql', 'list', 'mysql'),
        ('10.5.0-mariadb', 'dict', 'mariadb'),
        ('10.5.1-mariadb', 'list', 'mariadb'),
    ]
)
def test_get_server_implamentation(cursor_return_version, cursor_return_type, server_implementation):
    """
    Test that server implementation are handled properly by get_server_implementation() whether the server version returned as a list or dict.
    """
    cursor = dummy_cursor_class(cursor_return_version, cursor_return_type)

    assert get_server_implementation(cursor) == server_implementation
