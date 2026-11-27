# -*- coding: utf-8 -*-

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

from ansible_collections.ansible.mariadb.plugins.modules import mariadb_password_policy
from ansible_collections.ansible.mariadb.plugins.modules.mariadb_password_policy import (
    MySQLPasswordPolicy,
    normalize_int_value,
)


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

        raise AssertionError('Unexpected query: %s' % query)

    def fetchall(self):
        return list(self._rows)


class ModuleStub(object):
    def fail_json(self, **kwargs):
        raise RuntimeError(kwargs['msg'])


@pytest.mark.parametrize(
    'value,expected',
    [
        ('12', 12),
        (12, 12),
    ],
)
def test_normalize_int_value_returns_expected_int(value, expected):
    assert normalize_int_value(value) == expected



def test_configure_uses_mariadb_simple_password_check_mapping():
    cursor = FakeCursor({
        'simple_password_check_minimal_length': '12',
        'simple_password_check_letters_same_case': '2',
        'simple_password_check_digits': '2',
        'simple_password_check_other_characters': '1',
    })

    policy = MySQLPasswordPolicy(ModuleStub(), cursor, 'mariadb')

    result = policy.configure({
        'length': 12,
        'mixed_case_count': 2,
        'number_count': 2,
        'special_char_count': 1,
    })

    assert result['changed'] is False
    assert result['settings'] == {
        'length': 12,
        'mixed_case_count': 2,
        'number_count': 2,
        'special_char_count': 1,
    }


def test_configure_fails_when_requested_validation_facility_is_missing():
    policy = MySQLPasswordPolicy(ModuleStub(), FakeCursor({}), 'mariadb')

    with pytest.raises(RuntimeError) as exc_info:
        policy.configure({'length': 12})

    assert str(exc_info.value) == 'Password policy setting "length" is not available on this server.'


def test_read_setting_returns_mapped_mariadb_variable_name_and_value():
    policy = MySQLPasswordPolicy(
        ModuleStub(),
        FakeCursor({'simple_password_check_minimal_length': '12'}),
        'mariadb',
    )

    variable_name, value = policy.read_setting('length')

    assert variable_name == 'simple_password_check_minimal_length'
    assert value == '12'


def test_normalize_value_handles_supported_setting_types():
    policy = MySQLPasswordPolicy(ModuleStub(), FakeCursor({}), 'mariadb')

    assert policy.normalize_value('length', '12') == 12


def test_format_set_query_formats_expected_statement():
    assert MySQLPasswordPolicy.format_set_query('simple_password_check_minimal_length', 12) == (
        "SET GLOBAL `simple_password_check_minimal_length` = 12"
    )


def test_main_returns_configure_result(monkeypatch):
    with set_module_args(
        {
            'login_unix_socket': '/run/mysqld/mysqld.sock',
            'length': 12,
        }
    ):
        monkeypatch.setattr(AnsibleModule, 'exit_json', exit_json)
        monkeypatch.setattr(AnsibleModule, 'fail_json', fail_json)
        monkeypatch.setattr(mariadb_password_policy, 'driver', object())
        monkeypatch.setattr(mariadb_password_policy, 'connect', lambda *args, **kwargs: (MagicMock(), MagicMock()))

        def fake_configure(self, desired_settings, mode='global', check_mode=False):
            assert desired_settings['length'] == 12
            assert mode == 'global'
            assert check_mode is False
            return {
                'changed': False,
                'queries': [],
                'settings': {'length': 12},
            }

        monkeypatch.setattr(mariadb_password_policy.MySQLPasswordPolicy, 'configure', fake_configure)

        with pytest.raises(AnsibleExitJson) as exc:
            mariadb_password_policy.main()

    assert exc.value.args[0] == {
        'changed': False,
        'queries': [],
        'settings': {'length': 12},
    }
