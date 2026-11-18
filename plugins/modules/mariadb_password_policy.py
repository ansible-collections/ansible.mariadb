#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_password_policy

short_description: Manage MariaDB password policy settings

description:
  - Manage password policy settings on MariaDB.
  - This module is configuration-only and does not install or uninstall password validation components or plugins.
  - This module manages the C(simple_password_check) plugin settings only.

author:
  - Steve Fulmer (@stevefulme1)
  - Ron Gershburg (@ronger4)

version_added: '5.2.0'

options:
  length:
    description:
      - Minimum number of characters in a password.
    type: int
  mixed_case_count:
    description:
      - Minimum number of lowercase and uppercase letters required each by C(simple_password_check).
    type: int
  number_count:
    description:
      - Minimum number of numeric characters required.
    type: int
  special_char_count:
    description:
      - Minimum number of non-alphanumeric characters required.
    type: int

notes:
  - The C(simple_password_check) plugin must already be enabled on the target server.
  - The module does not install MariaDB password validation plugins.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

seealso:
  - module: ansible.mariadb.mariadb_query
  - module: ansible.mariadb.mariadb_variables
  - name: MariaDB simple password check plugin
    description: MariaDB reference for simple_password_check.
    link: https://mariadb.com/docs/server/reference/plugins/password-validation-plugins/simple-password-check-plugin

extends_documentation_fragment:
  - ansible.mariadb.mysql
'''

EXAMPLES = r'''
- name: Configure MariaDB simple_password_check settings
  ansible.mariadb.mariadb_password_policy:
    login_unix_socket: /run/mysqld/mysqld.sock
    length: 14
    mixed_case_count: 2
    number_count: 2
    special_char_count: 2
'''

RETURN = r'''
queries:
  description: List of executed or predicted (in check mode) SQL statements.
  returned: always
  type: list
  elements: str
  sample:
    - SET GLOBAL simple_password_check_minimal_length = 12
settings:
  description: Normalized requested settings after execution or prediction (in check mode).
  returned: always
  type: dict
  sample:
    length: 12
    number_count: 2
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mariadb.plugins.module_utils.database import mysql_quote_identifier
from ansible_collections.ansible.mariadb.plugins.module_utils.mysql import (
    mysql_common_argument_spec,
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
)


SETTING_VARIABLES = {
    'length': 'simple_password_check_minimal_length',
    'mixed_case_count': 'simple_password_check_letters_same_case',
    'number_count': 'simple_password_check_digits',
    'special_char_count': 'simple_password_check_other_characters',
}

INTEGER_OPTIONS = (
    'length',
    'mixed_case_count',
    'number_count',
    'special_char_count',
)


def normalize_int_value(value):
    if isinstance(value, int):
        return value

    return int(value)


def get_variable(cursor, mysqlvar):
    cursor.execute("SHOW GLOBAL VARIABLES WHERE Variable_name = %s", (mysqlvar,))
    rows = cursor.fetchall()
    return rows[0][1] if rows else None


def set_variable(cursor, mysqlvar, value):
    query = "SET GLOBAL %s = " % mysql_quote_identifier(mysqlvar, 'vars')
    cursor.execute(query + "%s", (value,))


class MariaDBPasswordPolicy(object):
    def __init__(self, module, cursor):
        self.module = module
        self.cursor = cursor

    def configure(self, desired_settings, check_mode=False):
        effective_settings = {}
        planned_changes = []

        for setting_name, desired_value in desired_settings.items():
            if desired_value is None:
                continue

            variable_name, current_value = self.read_setting(setting_name)
            normalized_current = self.normalize_value(setting_name, current_value)
            normalized_desired = self.normalize_value(setting_name, desired_value)

            effective_settings[setting_name] = normalized_desired

            if normalized_current != normalized_desired:
                planned_changes.append(
                    (setting_name, variable_name, self.query_value(setting_name, normalized_desired))
                )

        queries = []
        changed = bool(planned_changes)

        if check_mode:
            for _setting_name, variable_name, query_value in planned_changes:
                queries.append(self.format_set_query(variable_name, query_value))
            return dict(changed=changed, queries=queries, settings=effective_settings)

        for _setting_name, variable_name, query_value in planned_changes:
            try:
                set_variable(self.cursor, variable_name, query_value)
            except Exception as exc:
                self.module.fail_json(
                    msg='Failed to set %s: %s' % (variable_name, to_native(exc)),
                    changed=False,
                )
            queries.append(self.format_set_query(variable_name, query_value))

        return dict(changed=changed, queries=queries, settings=effective_settings)

    def read_setting(self, setting_name):
        variable_name = SETTING_VARIABLES[setting_name]
        value = get_variable(self.cursor, variable_name)
        if value is not None:
            return variable_name, value

        self.module.fail_json(
            msg='Password policy setting "%s" is not available on this server.' % setting_name,
            changed=False,
        )

    def normalize_value(self, setting_name, value):
        if setting_name in INTEGER_OPTIONS:
            return normalize_int_value(value)
        return value

    def query_value(self, setting_name, normalized_value):
        return normalized_value

    @staticmethod
    def format_set_query(variable_name, value):
        return "SET GLOBAL %s = %s" % (mysql_quote_identifier(variable_name, 'vars'), value)


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        length=dict(type='int'),
        mixed_case_count=dict(type='int'),
        number_count=dict(type='int'),
        special_char_count=dict(type='int'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        required_one_of=[(
            'length',
            'mixed_case_count',
            'number_count',
            'special_char_count',
        )],
        supports_check_mode=True,
    )

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    try:
        cursor, _db_conn = mysql_connect(
            module,
            module.params['login_user'],
            module.params['login_password'],
            module.params['config_file'],
            module.params['client_cert'],
            module.params['client_key'],
            module.params['ca_cert'],
            'mysql',
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
        )
    except Exception as exc:
        module.fail_json(
            msg="unable to connect to database, check login_user and "
                "login_password are correct or %s has the credentials. "
                "Exception message: %s" % (module.params['config_file'], to_native(exc))
        )

    desired_settings = {
        'length': module.params['length'],
        'mixed_case_count': module.params['mixed_case_count'],
        'number_count': module.params['number_count'],
        'special_char_count': module.params['special_char_count'],
    }

    password_policy = MariaDBPasswordPolicy(module, cursor)
    module.exit_json(
        **password_policy.configure(
            desired_settings,
            check_mode=module.check_mode,
        )
    )


if __name__ == '__main__':
    main()
