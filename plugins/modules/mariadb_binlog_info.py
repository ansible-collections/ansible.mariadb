#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_binlog_info

short_description: Gather MySQL or MariaDB binary log information

description:
  - Gather binary log information from MySQL or MariaDB servers.
  - Returns the current binary log status, available binary log files, aggregate log totals,
    and selected binary-log-related settings.
  - This module is read-only. Use M(ansible.mariadb.mariadb_variables) for mutable binlog settings.

author:
  - Ron Gershburg (@rgershbu)

version_added: '5.1.0'

options:
  filter:
    description:
      - Limit the collected information by comma separated string or YAML list.
      - Allowable values are V(current), V(logs), V(totals), and V(settings).
      - By default, collects all subsets.
      - You can use C(!) before a value, for example V(!settings), to exclude it from the information.
      - If you pass including and excluding values together, the excluding values are ignored.
    type: list
    elements: str

notes:
  - Compatible with MariaDB or MySQL.
  - The module does not modify server state.
  - The module requires binary logging to be enabled and fails when C(log_bin=OFF).
  - Some mutable binlog settings are dynamic and can be managed with M(ansible.mariadb.mariadb_variables).
  - Startup-only or restart-managed settings remain outside this module's scope.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

seealso:
  - module: ansible.mariadb.mariadb_variables
  - module: ansible.mariadb.mariadb_replication

extends_documentation_fragment:
  - ansible.mariadb.mysql
'''

EXAMPLES = r'''
- name: Collect all binlog information
  ansible.mariadb.mariadb_binlog_info:
    login_user: root
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Collect only current binlog status and log list
  ansible.mariadb.mariadb_binlog_info:
    login_user: root
    login_password: rootpass
    filter:
      - current
      - logs

- name: Collect all binlog info except settings
  ansible.mariadb.mariadb_binlog_info:
    login_user: root
    login_password: rootpass
    filter:
      - "!settings"
'''

RETURN = r'''
current:
  description: Current binary log status information.
  returned: if not excluded by filter
  type: dict
  sample:
    file: primary-bin.000003
    position: 158
    executed_gtid_set: "3E11FA47-71CA-11E1-9E33-C80AA9429562:1-1234"
logs:
  description: List of binary log files.
  returned: if not excluded by filter
  type: list
  elements: dict
  sample:
    - name: primary-bin.000001
      size: 181
      encrypted: 'No'
    - name: primary-bin.000002
      size: 2997943
      encrypted: 'No'
    - name: primary-bin.000003
      size: 158
      encrypted: 'No'
totals:
  description: Aggregate information about binary log files.
  returned: if not excluded by filter
  type: dict
  sample:
    count: 3
    size: 2998282
settings:
  description: Selected binary-log-related global settings.
  returned: if not excluded by filter
  type: dict
  sample:
    log_bin: 'ON'
    binlog_format: ROW
    max_binlog_size: 1073741824
    sync_binlog: 1
    binlog_expire_logs_seconds: 2592000
    binlog_encryption: 'OFF'
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mariadb.plugins.module_utils.command_resolver import (
    CommandResolver,
)
from ansible_collections.ansible.mariadb.plugins.module_utils.mysql import (
    get_server_implementation,
    get_server_version,
    mysql_common_argument_spec,
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
)


class MySQL_Binlog_Info(object):
    SETTINGS_VARS = (
        'log_bin',
        'binlog_format',
        'max_binlog_size',
        'sync_binlog',
        'binlog_expire_logs_seconds',
        'expire_logs_days',
        'binlog_encryption',
        'encrypt_binlog',
    )

    def __init__(self, module, cursor, server_implementation, server_version):
        self.module = module
        self.cursor = cursor
        self.server_implementation = server_implementation
        self.command_resolver = CommandResolver(server_implementation, server_version)
        self.info = {
            'current': {},
            'logs': [],
            'totals': {},
            'settings': {},
        }

    def get_info(self, filter_):
        wanted = set(self.__get_wanted(filter_))
        self.__ensure_binary_logging_enabled()
        self.__collect(wanted)
        return dict((key, self.info[key]) for key in self.info if key in wanted)

    def __get_wanted(self, filter_):
        if not filter_:
            return self.info

        included = []
        excluded = []

        for item in filter_:
            key = item.lstrip('!')
            if key not in self.info:
                continue

            if item.startswith('!'):
                excluded.append(key)
            else:
                included.append(key)

        if included:
            return included

        return [key for key in self.info if key not in excluded]

    def __collect(self, wanted):
        if 'current' in wanted:
            self.__get_current_status()

        if 'logs' in wanted or 'totals' in wanted:
            self.__get_logs()

        if 'totals' in wanted:
            self.info['totals'] = {
                'count': len(self.info['logs']),
                'size': sum(log['size'] for log in self.info['logs']),
            }

        if 'settings' in wanted:
            self.__get_settings()

    def __ensure_binary_logging_enabled(self):
        res = self.__exec_sql("SHOW GLOBAL VARIABLES LIKE 'log_bin'")
        if not res:
            return

        log_bin = res[0].get('Value')
        if str(log_bin).upper() in ('OFF', '0'):
            self.module.fail_json(
                msg='Binary logging is disabled (log_bin=OFF), mysql_binlog_info cannot be used.'
            )

    def __get_current_status(self):
        query = self.command_resolver.resolve_command("SHOW MASTER STATUS")
        res = self.__exec_sql(query)
        if not res:
            return

        current = res[0]
        executed_gtid_set = current.get('Executed_Gtid_Set') or current.get('Gtid_Binlog_Pos')

        if executed_gtid_set is None and self.server_implementation == 'mariadb':
            gtid_res = self.__exec_sql('SELECT @@global.gtid_binlog_pos AS gtid_binlog_pos')
            if gtid_res:
                executed_gtid_set = gtid_res[0].get('gtid_binlog_pos')

        self.info['current'] = {
            'file': current.get('File'),
            'position': self.__convert(current.get('Position')),
            'executed_gtid_set': executed_gtid_set,
        }

    def __get_logs(self):
        res = self.__exec_sql('SHOW BINARY LOGS')
        self.info['logs'] = []

        if not res:
            return

        for line in res:
            self.info['logs'].append({
                'name': line.get('Log_name'),
                'size': self.__convert(line.get('File_size')),
                'encrypted': line.get('Encrypted'),
            })

    def __get_settings(self):
        res = self.__exec_sql('SHOW GLOBAL VARIABLES')
        self.info['settings'] = {}

        if not res:
            return

        for line in res:
            variable_name = line.get('Variable_name')
            if variable_name in self.SETTINGS_VARS:
                self.info['settings'][variable_name] = self.__convert(line.get('Value'))

    def __exec_sql(self, query):
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except Exception as e:
            self.module.fail_json(msg="Cannot execute SQL '%s': %s" % (query, to_native(e)))
        return False

    @staticmethod
    def __convert(val):
        try:
            return int(val)
        except (TypeError, ValueError):
            return val


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        filter=dict(type='list', elements='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    connect_timeout = module.params['connect_timeout']
    login_user = module.params['login_user']
    login_password = module.params['login_password']
    ssl_cert = module.params['client_cert']
    ssl_key = module.params['client_key']
    ssl_ca = module.params['ca_cert']
    check_hostname = module.params['check_hostname']
    config_file = module.params['config_file']
    filter_ = module.params['filter']

    if filter_:
        filter_ = [item.strip() for item in filter_]

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

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
            check_hostname=check_hostname,
            connect_timeout=connect_timeout,
            cursor_class='DictCursor',
        )
    except Exception as e:
        module.fail_json(
            msg="unable to connect to database, check login_user and "
                "login_password are correct or %s has the credentials. "
                "Exception message: %s" % (config_file, to_native(e))
        )

    server_implementation = get_server_implementation(cursor)
    server_version = get_server_version(cursor)

    mysql = MySQL_Binlog_Info(module, cursor, server_implementation, server_version)

    module.exit_json(changed=False, **mysql.get_info(filter_))


if __name__ == '__main__':
    main()
