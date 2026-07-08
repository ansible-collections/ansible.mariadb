#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_slow_log

short_description: Manage MySQL or MariaDB slow query log settings

description:
  - Manage MySQL or MariaDB slow query log runtime settings.
  - Supports enabling the slow query log, setting thresholds and output, and rotating file-based slow logs.

author:
  - Ron Gershburg (@ronger4)

version_added: '5.1.0'

options:
  enabled:
    description:
      - Enable or disable the slow query log.
    type: bool
  long_query_time:
    description:
      - Log queries that run longer than this number of seconds.
    type: float
  log_output:
    description:
      - Output destination for the slow query log.
      - Use V(FILE,TABLE) to log to both destinations.
      - The module normalizes V(TABLE,FILE) to V(FILE,TABLE).
    type: str
    choices:
      - FILE
      - TABLE
      - NONE
      - FILE,TABLE
      - TABLE,FILE
  log_queries_not_using_indexes:
    description:
      - Whether to log queries that do not use indexes.
    type: bool
  min_examined_row_limit:
    description:
      - Log only queries that examine at least this many rows.
    type: int
  flush:
    description:
      - Rotate the slow query log by executing C(FLUSH SLOW LOGS).
      - This requires the effective O(log_output) to include V(FILE).
      - This action is not idempotent and always reports a change when requested.
    type: bool
    default: false

notes:
  - Compatible with MariaDB or MySQL.
  - The module manages global runtime slow-log settings only.
  - The O(flush) action requires the server privilege needed to execute C(FLUSH SLOW LOGS).

attributes:
  check_mode:
    support: full
  idempotent:
    support: partial
    details:
      - Setting changes are idempotent.
      - When O(flush=true) is requested, the module always reports a change.

seealso:
  - module: ansible.mariadb.mariadb_info
  - module: ansible.mariadb.mariadb_query
  - module: ansible.mariadb.mariadb_variables

extends_documentation_fragment:
  - ansible.mariadb.mysql
'''

EXAMPLES = r'''
- name: Enable slow query logging to a file with a one second threshold
  ansible.mariadb.mariadb_slow_log:
    login_user: root
    login_password: rootpass
    enabled: true
    long_query_time: 1
    log_output: FILE
    min_examined_row_limit: 100

- name: Enable verbose slow query logging in development
  ansible.mariadb.mariadb_slow_log:
    login_user: root
    login_password: rootpass
    enabled: true
    long_query_time: 0.5
    log_output: TABLE
    log_queries_not_using_indexes: true

- name: Rotate a file-based slow query log
  ansible.mariadb.mariadb_slow_log:
    login_user: root
    login_password: rootpass
    flush: true
'''

RETURN = r'''
queries:
  description: List of executed queries which modified DB state.
  returned: always
  type: list
  sample:
    - SET GLOBAL `slow_query_log` = ON
    - FLUSH SLOW LOGS
settings:
  description: Effective slow query log settings after applying requested changes.
  returned: always
  type: dict
  sample:
    enabled: 'ON'
    long_query_time: 1.0
    log_output: FILE
    log_queries_not_using_indexes: 'OFF'
    min_examined_row_limit: 100
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mysql.plugins.module_utils.database import mysql_quote_identifier
from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    get_server_implementation,
    mysql_common_argument_spec,
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
)


def typedvalue(value):
    """Convert value to number whenever possible, return the same value otherwise."""
    if isinstance(value, (bool, int, float)):
        return value

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def get_variable(cursor, mysqlvar):
    cursor.execute("SHOW GLOBAL VARIABLES WHERE Variable_name = %s", (mysqlvar,))
    mysqlvar_val = cursor.fetchall()
    if len(mysqlvar_val) == 1:
        return mysqlvar_val[0][1]
    else:
        return None


def set_variable(cursor, mysqlvar, value, executed_queries):
    query = "SET GLOBAL %s = " % mysql_quote_identifier(mysqlvar, 'vars')
    try:
        cursor.execute(query + "%s", (value,))
        executed_queries.append(query + "%s" % value)
        cursor.fetchall()
        result = True
    except Exception as e:
        result = to_native(e)

    return result


def convert_bool_setting_value_wanted(val):
    """Convert 0/1/on/off values to the ON/OFF representation used by the server."""
    if isinstance(val, str):
        val = val.upper()

    if val in ('ON', '1', 1, True):
        val = 'ON'
    elif val in ('OFF', '0', 0, False):
        val = 'OFF'

    return val


class MySQLSlowLog(object):
    VARIABLE_CANDIDATES = {
        'enabled': {
            'mysql': ('slow_query_log',),
            'mariadb': ('log_slow_query', 'slow_query_log'),
        },
        'long_query_time': {
            'mysql': ('long_query_time',),
            'mariadb': ('log_slow_query_time', 'long_query_time'),
        },
        'log_output': {
            'mysql': ('log_output',),
            'mariadb': ('log_output',),
        },
        'log_queries_not_using_indexes': {
            'mysql': ('log_queries_not_using_indexes',),
            'mariadb': ('log_queries_not_using_indexes',),
        },
        'min_examined_row_limit': {
            'mysql': ('min_examined_row_limit',),
            'mariadb': ('log_slow_min_examined_row_limit', 'min_examined_row_limit'),
        },
    }

    def __init__(self, module, cursor, server_implementation):
        self.module = module
        self.cursor = cursor
        self.server_implementation = server_implementation
        self.variable_names = {}

    def configure(self, desired_settings, flush=False, check_mode=False):
        current_settings = self.get_current_settings()
        effective_settings = current_settings.copy()
        planned_changes = []

        for setting_name, value in desired_settings.items():
            if value is None:
                continue

            normalized_value = self.normalize_value(setting_name, value)
            effective_settings[setting_name] = normalized_value

            if normalized_value != current_settings[setting_name]:
                planned_changes.append((setting_name, self.variable_names[setting_name], normalized_value))

        if flush:
            self.validate_flush(effective_settings['log_output'])

        changed = bool(planned_changes) or flush
        queries = []

        if check_mode:
            for _setting_name, variable_name, value in planned_changes:
                queries.append(self.format_set_query(variable_name, value))

            if flush:
                queries.append('FLUSH SLOW LOGS')

            return dict(changed=changed, queries=queries, settings=effective_settings)

        for _setting_name, variable_name, value in planned_changes:
            result = set_variable(self.cursor, variable_name, value, queries)
            if result is not True:
                self.module.fail_json(msg=result, changed=False)

        if flush:
            try:
                self.cursor.execute('FLUSH SLOW LOGS')
                self.cursor.fetchall()
            except Exception as e:
                self.module.fail_json(msg="Cannot execute SQL 'FLUSH SLOW LOGS': %s" % to_native(e))
            queries.append('FLUSH SLOW LOGS')

        return dict(changed=changed, queries=queries, settings=effective_settings)

    def get_current_settings(self):
        settings = {}

        for setting_name in self.VARIABLE_CANDIDATES:
            variable_name, value = self.read_setting(setting_name)
            self.variable_names[setting_name] = variable_name
            settings[setting_name] = self.normalize_value(setting_name, value)

        return settings

    def read_setting(self, setting_name):
        for variable_name in self.VARIABLE_CANDIDATES[setting_name][self.server_implementation]:
            value = get_variable(self.cursor, variable_name)
            if value is not None:
                return variable_name, value

        self.module.fail_json(
            msg='Slow log setting "%s" is not available on this server.' % setting_name,
            changed=False,
        )

    def normalize_value(self, setting_name, value):
        if setting_name in ('enabled', 'log_queries_not_using_indexes'):
            return convert_bool_setting_value_wanted(value)
        if setting_name == 'log_output':
            return self.normalize_log_output(value)
        return typedvalue(value)

    def normalize_log_output(self, value):
        output_parts = []
        for part in str(value).split(','):
            part = part.strip().upper()
            if part and part not in output_parts:
                output_parts.append(part)

        allowed_values = ('FILE', 'TABLE', 'NONE')
        if not output_parts or any(part not in allowed_values for part in output_parts):
            self.module.fail_json(msg='log_output must be FILE, TABLE, NONE, or FILE,TABLE')

        if 'NONE' in output_parts and len(output_parts) > 1:
            self.module.fail_json(msg='log_output cannot combine NONE with other values')

        if set(output_parts) == set(['FILE', 'TABLE']):
            return 'FILE,TABLE'

        return output_parts[0]

    def validate_flush(self, log_output):
        if 'FILE' not in log_output.split(','):
            self.module.fail_json(msg='flush requires FILE log_output')

    @staticmethod
    def format_set_query(variable_name, value):
        return "SET GLOBAL `%s` = %s" % (variable_name, value)


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        enabled=dict(type='bool'),
        long_query_time=dict(type='float'),
        log_output=dict(type='str', choices=['FILE', 'TABLE', 'NONE', 'FILE,TABLE', 'TABLE,FILE']),
        log_queries_not_using_indexes=dict(type='bool'),
        min_examined_row_limit=dict(type='int'),
        flush=dict(type='bool', default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    connect_timeout = module.params['connect_timeout']
    login_user = module.params['login_user']
    login_password = module.params['login_password']
    ssl_cert = module.params['client_cert']
    ssl_key = module.params['client_key']
    ssl_ca = module.params['ca_cert']
    check_hostname = module.params['check_hostname']
    config_file = module.params['config_file']

    try:
        cursor, _db_conn = mysql_connect(
            module,
            login_user,
            login_password,
            config_file,
            ssl_cert,
            ssl_key,
            ssl_ca,
            'mysql',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname,
        )
    except Exception as e:
        module.fail_json(
            msg="unable to connect to database, check login_user and "
                "login_password are correct or %s has the credentials. "
                "Exception message: %s" % (config_file, to_native(e))
        )

    desired_settings = {
        'enabled': module.params['enabled'],
        'long_query_time': module.params['long_query_time'],
        'log_output': module.params['log_output'],
        'log_queries_not_using_indexes': module.params['log_queries_not_using_indexes'],
        'min_examined_row_limit': module.params['min_examined_row_limit'],
    }

    slow_log = MySQLSlowLog(module, cursor, get_server_implementation(cursor))

    module.exit_json(
        **slow_log.configure(
            desired_settings,
            flush=module.params['flush'],
            check_mode=module.check_mode,
        )
    )


if __name__ == '__main__':
    main()
