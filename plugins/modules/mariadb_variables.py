#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2013, Balazs Pocze <banyek@gawker.com>
# Certain parts are taken from Mark Theunissen's mysqldb module
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_variables

short_description: Manage MariaDB global variables
description:
- Query and set MariaDB global variables.
author:
- Balazs Pocze (@banyek)
options:
  variable:
    description:
    - Variable name to operate.
    type: str
    required: true
  value:
    description:
    - If set, then sets variable value to this.
    - With boolean values, use C(0)|C(1) or quoted C("ON")|C("OFF").
    type: str

attributes:
  check_mode:
    support: none
  idempotent:
    support: partial
    details:
      - The module is idempotent when O(value) is not set (read-only query).
      - When setting a value, the module is idempotent.

seealso:
- module: ansible.mariadb.mariadb_info
- name: MariaDB SET command reference
  description: Complete reference of the MariaDB SET server system variables
  link: https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables

notes:
   - Compatible with MariaDB.

extends_documentation_fragment:
- ansible.mariadb.connect
'''

EXAMPLES = r'''
# If you encounter the "Please explicitly state intended protocol" error,
# use the login_unix_socket argument
- name: Check for sync_binlog setting
  ansible.mariadb.mariadb_variables:
    variable: sync_binlog
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Set read_only variable to 1
  ansible.mariadb.mariadb_variables:
    variable: read_only
    value: 1

- name: Set a boolean using ON/OFF notation
  mariadb_variables:
    variable: log_slow_replica_statements
    value: "ON"  # Make sure it's quoted
'''

RETURN = r'''
queries:
  description: List of executed queries which modified DB's state.
  returned: if executed
  type: list
  sample: ["SET GLOBAL `read_only` = 1"]
  version_added: '0.1.0'
'''

import os
import warnings
from re import match

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ansible.mariadb.plugins.module_utils.connect import connect, driver, driver_fail_msg, common_argument_spec
from ansible.module_utils.common.text.converters import to_native
from ansible_collections.ansible.mariadb.plugins.module_utils.variable import (
    convert_bool,
    get_variable,
    set_variable,
    typedvalue,
)

executed_queries = []


def main():
    argument_spec = common_argument_spec()
    argument_spec.update(
        variable=dict(type='str', required=True),
        value=dict(type='str'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec
    )
    user = module.params["login_user"]
    password = module.params["login_password"]
    connect_timeout = module.params['connect_timeout']
    ssl_cert = module.params["client_cert"]
    ssl_key = module.params["client_key"]
    ssl_ca = module.params["ca_cert"]
    check_hostname = module.params["check_hostname"]
    config_file = module.params['config_file']
    db = 'mysql'

    var = module.params["variable"]
    value = module.params["value"]

    if var is None:
        module.fail_json(msg="Cannot run without variable to operate with")
    if match('^[0-9A-Za-z_.]+$', var) is None:
        module.fail_json(msg="invalid variable name \"%s\"" % var)
    if driver is None:
        module.fail_json(msg=driver_fail_msg)
    else:
        warnings.filterwarnings('error', category=driver.Warning)

    try:
        cursor, db_conn = connect(module, user, password, config_file, ssl_cert, ssl_key, ssl_ca, db,
                                  connect_timeout=connect_timeout, check_hostname=check_hostname)
    except Exception as e:
        if os.path.exists(config_file):
            module.fail_json(msg=("unable to connect to database, check login_user and "
                                  "login_password are correct or %s has the credentials. "
                                  "Exception message: %s" % (config_file, to_native(e))))
        else:
            module.fail_json(msg="unable to find %s. Exception message: %s" % (config_file, to_native(e)))

    var_val = get_variable(cursor, var)
    if var_val is None:
        module.fail_json(msg="Variable not available \"%s\"" % var, changed=False)

    if value is None:
        module.exit_json(msg=var_val)

    # Type values before using them
    value_wanted = typedvalue(value)
    value_actual = typedvalue(var_val)
    if value_actual in ('ON', 'OFF') and value_wanted not in ('ON', 'OFF'):
        value_wanted = convert_bool(value_wanted)

    if value_wanted == value_actual:
        module.exit_json(msg="Variable is already set to requested value.", changed=False)

    try:
        set_variable(cursor, var, value_wanted)
        executed_queries.append("SET GLOBAL `%s` = %s" % (var, value_wanted))
        cursor.fetchall()
        result = True
    except Exception as e:
        result = to_native(e)

    if result is True:
        module.exit_json(msg="Variable change succeeded prev_value=%s" % value_actual,
                         changed=True, queries=executed_queries)
    else:
        module.fail_json(msg=result, changed=False)


if __name__ == '__main__':
    main()
