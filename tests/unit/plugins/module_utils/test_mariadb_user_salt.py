# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mariadb.plugins.module_utils import user as user_utils
from ansible_collections.ansible.mariadb.plugins.module_utils.implementations.mysql.hash import (
    mysql_sha256_password_hash,
)


class RecordingCursor(object):
    def __init__(self):
        self.queries = []

    def execute(self, query, args=None):
        self.queries.append((query, args))


class FakeImpl(object):
    @staticmethod
    def use_old_user_mgmt(cursor):
        return False


class FakeModule(object):
    check_mode = False

    def fail_json(self, **kwargs):
        raise AssertionError(kwargs)


@pytest.mark.parametrize('plugin', ['caching_sha2_password', 'sha256_password'])
def test_user_add_with_salt_uses_quoted_hash(monkeypatch, plugin):
    """MariaDB rejects 'AS 0x...' hex literals (issue #28); the hash must be a string."""
    monkeypatch.setattr(user_utils, 'get_user_implementation', lambda cursor: FakeImpl)
    cursor = RecordingCursor()
    salt = 'TDwqdanU82d0yNtvaabb'

    user_utils.user_add(
        cursor, 'u1', '%', False, None, False,
        plugin, None, 'secret', salt, None,
        None, None, False, FakeModule(), None, None,
    )

    query, args = cursor.queries[0]
    assert '0x' not in query
    assert query == 'CREATE USER %s@%s IDENTIFIED WITH %s AS %s'
    assert args == ('u1', '%', plugin, mysql_sha256_password_hash(password='secret', salt=salt))
    assert args[3].startswith('$A$005$' + salt)
