# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from unittest.mock import MagicMock, call, patch

import pytest

from ansible_collections.ansible.mariadb.plugins.module_utils.user import (
    _get_plugin_auth_clause,
    _privileges_mod,
    handle_grant_on_col,
    has_grant_on_col,
    normalize_col_grants,
    sort_column_order,
    privileges_get,
    privileges_grant,
    privileges_revoke,
    privileges_unpack,
)


@pytest.mark.parametrize(
    'plugin,plugin_hash_string,plugin_auth_string,salt,expected',
    [
        ('mysql_native_password', '*hash', None, None, ('*hash', ' AS %s', ('*hash',))),
        ('pam', None, 'system-auth', None, ('system-auth', ' USING %s', ('system-auth',))),
        ('ed25519', None, 'secret', None, ('secret', ' USING PASSWORD(%s)', ('secret',))),
        ('parsec', None, 'secret', None, ('secret', ' USING PASSWORD(%s)', ('secret',))),
        ('caching_sha2_password', None, 'secret', None, ('secret', ' BY %s', ('secret',))),
        (
            'caching_sha2_password', None, 'password', '1234567890abcdefghij',
            (
                '$A$005$1234567890abcdefghijZhkXqsPwdUcxIevlDledVLOK0Oqn.RxGRi3b./OHKW/',
                (
                    ' AS 0x24412430303524313233343536373839306162636465666768696A5A686B5871735077645563784965766C'
                    '446C6564564C4F4B304F716E2E527847526933622E2F4F484B572F'
                ),
                (),
            ),
        ),
        ('mysql_native_password', None, None, None, (None, '', ())),
    ],
)
def test_get_plugin_auth_clause(plugin, plugin_hash_string, plugin_auth_string, salt, expected):
    assert _get_plugin_auth_clause(plugin, plugin_hash_string, plugin_auth_string, salt) == expected


@pytest.mark.parametrize('role,user,host', [
    (False, 'user2', 'localhost'),
    (True, 'reader', ''),
])
def test_privileges_mod_idempotency(role, user, host):
    cursor = MagicMock()
    priv = {'*.*': ['SELECT']}
    get_path = 'ansible_collections.ansible.mariadb.plugins.module_utils.user.privileges_get'

    with patch(get_path, return_value=priv) as privileges_get:
        result = _privileges_mod(
            cursor, user, host, priv, False, False, None, False, role=role)

    assert result == (False, None, False)
    assert privileges_get.call_args_list == [
        call(cursor, user, host, role),
        call(cursor, user, host, role),
    ]


@pytest.mark.parametrize('role,user,host', [
    (False, 'user2', 'localhost'),
    (True, 'reader', ''),
])
def test_privileges_mod_grants_missing_privileges(role, user, host):
    cursor = MagicMock()
    module_path = 'ansible_collections.ansible.mariadb.plugins.module_utils.user'
    current_priv = {'*.*': ['SELECT']}
    updated_priv = {'*.*': ['SELECT', 'INSERT']}

    with patch(module_path + '.privileges_get', side_effect=[current_priv, updated_priv]), \
            patch(module_path + '.privileges_grant') as privileges_grant:
        result = _privileges_mod(
            cursor, user, host, updated_priv, False, False, None, False, role=role)

    assert result == (True, "Privileges updated: granted ['INSERT'], revoked []", False)
    privileges_grant.assert_called_once_with(
        cursor, user, host, '*.*', ['INSERT'], None, role)


@pytest.mark.parametrize(
    'input_list,grant,output_tuple',
    [
        (['INSERT', 'DELETE'], 'INSERT', (None, None)),
        (['SELECT', 'UPDATE'], 'SELECT', (None, None)),
        (['INSERT', 'UPDATE', 'INSERT', 'DELETE'], 'DELETE', (None, None)),
        (['just', 'a', 'random', 'text'], 'blabla', (None, None)),
        (['SELECT (A, B, C)'], 'SELECT', (0, 0)),
        (['UPDATE', 'SELECT (A, B, C)'], 'SELECT', (1, 1)),
        (['UPDATE', 'REFERENCES (A, B, C)'], 'REFERENCES', (1, 1)),
        (['SELECT', 'UPDATE (A, B, C)'], 'UPDATE', (1, 1)),
        (['INSERT', 'SELECT (A', 'B)'], 'SELECT', (1, 2)),
        (['SELECT (A', 'B)', 'UPDATE'], 'SELECT', (0, 1)),
        (['INSERT', 'SELECT (A', 'B)', 'UPDATE'], 'SELECT', (1, 2)),
        (['INSERT (A, B)', 'SELECT (A', 'B)', 'UPDATE'], 'INSERT', (0, 0)),
        (['INSERT (A', 'B)', 'SELECT (A', 'B)', 'UPDATE'], 'INSERT', (0, 1)),
        (['INSERT (A', 'B)', 'SELECT (A', 'B)', 'UPDATE'], 'SELECT', (2, 3)),
        (['INSERT (A', 'B)', 'SELECT (A', 'C', 'B)', 'UPDATE'], 'SELECT', (2, 4)),
    ]
)
def test_has_grant_on_col(input_list, grant, output_tuple):
    """Tests has_grant_on_col function."""
    assert has_grant_on_col(input_list, grant) == output_tuple


@pytest.mark.parametrize(
    'input_,output',
    [
        ('SELECT (A)', 'SELECT (A)'),
        ('SELECT (`A`)', 'SELECT (A)'),
        ('UPDATE (B, A)', 'UPDATE (A, B)'),
        ('INSERT (`A`, `B`)', 'INSERT (A, B)'),
        ('REFERENCES (B, A)', 'REFERENCES (A, B)'),
        ('SELECT (`B`, `A`)', 'SELECT (A, B)'),
        ('SELECT (`B`, `A`, C)', 'SELECT (A, B, C)'),
    ]
)
def test_sort_column_order(input_, output):
    """Tests sort_column_order function."""
    assert sort_column_order(input_) == output


@pytest.mark.parametrize(
    'privileges,start,end,output',
    [
        (['UPDATE', 'SELECT (C, B, A)'], 1, 1, ['UPDATE', 'SELECT (A, B, C)']),
        (['INSERT', 'SELECT (A', 'B)'], 1, 2, ['INSERT', 'SELECT (A, B)']),
        (
            ['SELECT (`A`', 'B)', 'UPDATE', 'REFERENCES (B, A)'], 0, 1,
            ['SELECT (A, B)', 'UPDATE', 'REFERENCES (B, A)']),
        (
            ['INSERT', 'REFERENCES (`B`', 'A', 'C)', 'UPDATE (A', 'B)'], 1, 3,
            ['INSERT', 'REFERENCES (A, B, C)', 'UPDATE (A', 'B)']),
    ]
)
def test_handle_grant_on_col(privileges, start, end, output):
    """Tests handle_grant_on_col function."""
    assert handle_grant_on_col(privileges, start, end) == output


@pytest.mark.parametrize(
    'input_,expected',
    [
        (['SELECT'], ['SELECT']),
        (['SELECT (A, B)'], ['SELECT (A, B)']),
        (['SELECT (B, A)'], ['SELECT (A, B)']),
        (['UPDATE', 'SELECT (C, B, A)'], ['UPDATE', 'SELECT (A, B, C)']),
        (['INSERT', 'SELECT (A', 'B)'], ['INSERT', 'SELECT (A, B)']),
        (
            ['SELECT (`A`', 'B)', 'UPDATE', 'REFERENCES (B, A)'],
            ['SELECT (A, B)', 'UPDATE', 'REFERENCES (A, B)']),
        (
            ['INSERT', 'REFERENCES (`B`', 'A', 'C)', 'UPDATE (B', 'A)', 'DELETE'],
            ['INSERT', 'REFERENCES (A, B, C)', 'UPDATE (A, B)', 'DELETE']),
    ]
)
def test_normalize_col_grants(input_, expected):
    """Tests normalize_col_grants function."""
    assert normalize_col_grants(input_) == expected


@pytest.mark.parametrize(
    'priv,expected,mode,column_case_sensitive,ensure_usage',
    [
        ('mydb.*:SELECT', {'"mydb".*': ['SELECT']}, 'ANSI', False, False),
        ('mydb.*:SELECT', {'`mydb`.*': ['SELECT']}, 'NOTANSI', False, False),
        ('mydb.*:SELECT', {'"mydb".*': ['SELECT'], '*.*': ['USAGE']}, 'ANSI', False, True),
        ('mydb.*:SELECT', {'`mydb`.*': ['SELECT'], '*.*': ['USAGE']}, 'NOTANSI', False, True),
        ('mydb.*:SELECT (a)', {'`mydb`.*': ['SELECT (A)']}, 'NOTANSI', False, False),
        ('mydb.*:UPDATE (b, a)', {'`mydb`.*': ['UPDATE (a, b)']}, 'NOTANSI', True, False),
        ('mydb.*:SELECT (b, a, c)', {'`mydb`.*': ['SELECT (A, B, C)']}, 'NOTANSI', False, False),
        ('mydb.*:SELECT (b, a, c)', {'`mydb`.*': ['SELECT (a, b, c)']}, 'NOTANSI', True, False),
    ]
)
def test_privileges_unpack(priv, mode, column_case_sensitive, ensure_usage, expected):
    """Tests privileges_unpack function."""
    assert privileges_unpack(priv, mode, column_case_sensitive, ensure_usage) == expected


@pytest.mark.parametrize(
    'role,grant,expected_query,expected_params,expected_privileges',
    [
        (
            False,
            "GRANT SELECT ON *.* TO `user2`@`localhost` WITH GRANT OPTION",
            'SHOW GRANTS FOR %s@%s',
            ('user2', 'localhost'),
            {'*.*': ['SELECT', 'GRANT']},
        ),
        (
            True,
            'GRANT SELECT ON *.* TO `reader`',
            'SHOW GRANTS FOR %s',
            ('reader',),
            {'*.*': ['SELECT']},
        ),
    ],
)
def test_privileges_get_uses_account_syntax(role, grant, expected_query, expected_params, expected_privileges):
    cursor = MagicMock()
    cursor.fetchall.return_value = [(grant,)]

    assert privileges_get(cursor, 'reader' if role else 'user2', '' if role else 'localhost', role) == expected_privileges
    cursor.execute.assert_called_once_with(expected_query, expected_params)


@pytest.mark.parametrize(
    'role,expected_query,expected_params',
    [
        (False, 'GRANT SELECT ON *.* TO %s@%s WITH GRANT OPTION', ('user2', 'localhost')),
        (True, 'GRANT SELECT ON *.* TO %s WITH GRANT OPTION', ('reader',)),
    ],
)
def test_privileges_grant_uses_account_syntax(role, expected_query, expected_params):
    cursor = MagicMock()

    privileges_grant(
        cursor,
        'reader' if role else 'user2',
        '' if role else 'localhost',
        '*.*',
        ['SELECT', 'GRANT'],
        None,
        role,
    )

    cursor.execute.assert_called_once_with(expected_query, expected_params)


@pytest.mark.parametrize(
    'role,expected_query,expected_params',
    [
        (False, 'REVOKE GRANT OPTION ON *.* FROM %s@%s', ('user2', 'localhost')),
        (True, 'REVOKE GRANT OPTION ON *.* FROM %s', ('reader',)),
    ],
)
def test_privileges_revoke_uses_account_syntax(role, expected_query, expected_params):
    cursor = MagicMock()

    privileges_revoke(
        cursor,
        'reader' if role else 'user2',
        '' if role else 'localhost',
        '*.*',
        ['GRANT'],
        True,
        role,
    )

    assert cursor.execute.call_args_list == [
        call(expected_query, expected_params),
        call('FLUSH PRIVILEGES'),
    ]
