# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mariadb.plugins.modules.mariadb_role import (
    normalize_users,
    role_create,
    role_exists,
    role_grant,
    role_revoke,
)

# TODO: Also cover DbServer and Role classes


class Module():
    def __init__(self):
        self.msg = None

    def fail_json(self, msg=None):
        self.msg = msg


module = Module()


@pytest.mark.parametrize(
    'name,output',
    [
        ('role0', ("SELECT count(*) FROM mysql.user WHERE user = %s AND is_role  = 'Y'", ('role0',))),
        ('role1', ("SELECT count(*) FROM mysql.user WHERE user = %s AND is_role  = 'Y'", ('role1',))),
    ]
)
def test_role_exists(name, output):
    """Test the role_exists function."""
    assert role_exists(name) == output


@pytest.mark.parametrize(
    'name,admin,output',
    [
        ('role0', None, ('CREATE ROLE %s', ('role0',))),
        ('role1', None, ('CREATE ROLE %s', ('role1',))),
        ('role0', ('user0', ''), ('CREATE ROLE %s WITH ADMIN %s', ('role0', 'user0'))),
        ('role1', ('user0', 'localhost'), ('CREATE ROLE %s WITH ADMIN %s@%s', ('role1', 'user0', 'localhost'))),
    ]
)
def test_role_create(name, admin, output):
    """Test the role_create function."""
    assert role_create(name, admin) == output


@pytest.mark.parametrize(
    'name,user,output',
    [
        ('role0', ('user0', ''), ('GRANT %s TO %s', ('role0', 'user0'))),
        ('role1', ('user0', 'localhost'), ('GRANT %s TO %s@%s', ('role1', 'user0', 'localhost'))),
    ]
)
def test_role_grant(name, user, output):
    """Test the role_grant function."""
    assert role_grant(name, user) == output


@pytest.mark.parametrize(
    'name,user,output',
    [
        ('role0', ('user0', ''), ('REVOKE %s FROM %s', ('role0', 'user0'))),
        ('role1', ('user0', 'localhost'), ('REVOKE %s FROM %s@%s', ('role1', 'user0', 'localhost'))),
    ]
)
def test_role_revoke(name, user, output):
    """Test the role_revoke function."""
    assert role_revoke(name, user) == output


@pytest.mark.parametrize(
    'input_,output',
    [
        (['user'], [('user', '')]),
        (['user@%'], [('user', '%')]),
        (['user@localhost'], [('user', 'localhost')]),
        (['user', 'user@%'], [('user', ''), ('user', '%')]),
    ]
)
def test_normalize_users(input_, output):
    """Test normalize_users function with expected input."""
    assert normalize_users(None, input_) == output


@pytest.mark.parametrize(
    'input_,err_msg',
    [
        ([''], "Member's name cannot be empty."),
        ([None], "Error occured while parsing"),
    ]
)
def test_normalize_users_failing(input_, err_msg):
    """Test normalize_users function with wrong input."""

    normalize_users(module, input_)
    assert err_msg in module.msg
