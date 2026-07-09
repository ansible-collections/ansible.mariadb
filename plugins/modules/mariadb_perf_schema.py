#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_perf_schema

short_description: Manage MariaDB Performance Schema setup tables

description:
  - This module only supports MariaDB; all MySQL-related options will be removed in the next releases. Use the C(ansible.mysql) collection for MySQL automation.
  - Manage runtime Performance Schema configuration through setup tables.
  - Supports instruments, consumers, actors, and objects.
  - Reconciles only the rows requested in the task and leaves unrelated rows untouched.
  - This module manages runtime state only. Restart-persistent Performance Schema configuration remains outside its scope.

author:
  - Ron Gershburg (@ronger4)

version_added: '5.1.0'

options:
  instruments:
    description:
      - Instrument rows to reconcile in C(performance_schema.setup_instruments).
      - Existing instrument rows are updated in place.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - Instrument name or pattern from C(performance_schema.setup_instruments), for example C(statement/%).
        type: str
        required: true
      enabled:
        description:
          - Whether the instrument should be enabled.
        type: bool
        required: true
      timed:
        description:
          - Whether the instrument should be timed.
        type: bool
        required: true
  consumers:
    description:
      - Consumer rows to reconcile in C(performance_schema.setup_consumers).
      - Existing consumer rows are updated in place.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - Consumer name.
        type: str
        required: true
      enabled:
        description:
          - Whether the consumer should be enabled.
        type: bool
        required: true
  actors:
    description:
      - Actor rows to reconcile in C(performance_schema.setup_actors).
    type: list
    elements: dict
    suboptions:
      user:
        description:
          - Account user pattern.
        type: str
        required: true
      host:
        description:
          - Account host pattern.
        type: str
        required: true
      role:
        description:
          - Role pattern.
        type: str
        required: true
      enabled:
        description:
          - Whether matching threads should be instrumented.
          - Required when C(state=present).
        type: bool
      history:
        description:
          - Whether history consumers should retain data for matching threads.
          - Required when C(state=present).
        type: bool
      state:
        description:
          - Whether the actor row should exist.
        type: str
        choices: [absent, present]
        default: present
  objects:
    description:
      - Object rows to reconcile in C(performance_schema.setup_objects).
    type: list
    elements: dict
    suboptions:
      object_type:
        description:
          - Object type stored in Performance Schema.
        type: str
        required: true
      object_schema:
        description:
          - Schema name pattern.
        type: str
        required: true
      object_name:
        description:
          - Object name pattern.
        type: str
        required: true
      enabled:
        description:
          - Whether the object should be instrumented.
          - Required when C(state=present).
        type: bool
      timed:
        description:
          - Whether the object should be timed.
          - Required when C(state=present).
        type: bool
      state:
        description:
          - Whether the object row should exist.
        type: str
        choices: [absent, present]
        default: present

notes:
  - Compatible with MariaDB or MySQL when the requested Performance Schema sections are available on the server.
  - The module requires Performance Schema to be enabled and the requested setup table columns to exist.
  - Changes are runtime only and are not persisted across restart by this module.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

seealso:
  - module: ansible.mariadb.mariadb_query
  - name: MySQL Performance Schema reference
    description: Oracle MySQL Performance Schema documentation.
    link: https://dev.mysql.com/doc/en/performance-schema.html
  - name: MariaDB Performance Schema overview
    description: MariaDB Performance Schema documentation.
    link: https://mariadb.com/docs/server/reference/system-tables/performance-schema/performance-schema-overview

extends_documentation_fragment:
  - ansible.mariadb.mysql
'''

EXAMPLES = r'''
- name: Apply a standard monitoring baseline profile
  ansible.mariadb.mariadb_perf_schema:
    login_unix_socket: /run/mysqld/mysqld.sock
    instruments:
      - name: statement/sql/select
        enabled: true
        timed: true
      - name: stage/sql/Opening_tables
        enabled: true
        timed: true
      - name: wait/io/table/sql/handler
        enabled: true
        timed: true
    consumers:
      - name: events_statements_history
        enabled: true
      - name: events_waits_current
        enabled: true

- name: Enable statement instrumentation for one instrument
  ansible.mariadb.mariadb_perf_schema:
    login_unix_socket: /run/mysqld/mysqld.sock
    instruments:
      - name: statement/sql/insert
        enabled: true
        timed: true

- name: Enable one consumer and add one actor row
  ansible.mariadb.mariadb_perf_schema:
    login_unix_socket: /run/mysqld/mysqld.sock
    consumers:
      - name: events_waits_current
        enabled: true
    actors:
      - user: app
        host: '%'
        role: '%'
        enabled: true
        history: false

- name: Remove one object rule
  ansible.mariadb.mariadb_perf_schema:
    login_unix_socket: /run/mysqld/mysqld.sock
    objects:
      - object_type: TABLE
        object_schema: reporting
        object_name: slow_queries
        state: absent
'''

RETURN = r'''
queries:
  description: List of executed SQL statements or predicted SQL statements in check mode.
  returned: when changed
  type: list
  sample:
    - "UPDATE performance_schema.setup_consumers SET ENABLED = 'YES' WHERE NAME = 'events_waits_current'"
instruments:
  description: Normalized requested instrument rows after module execution or prediction.
  returned: when O(instruments) is provided
  type: list
  elements: dict
  sample:
    - name: statement/sql/select
      enabled: true
      timed: true
consumers:
  description: Normalized requested consumer rows after module execution or prediction.
  returned: when O(consumers) is provided
  type: list
  elements: dict
  sample:
    - name: events_waits_current
      enabled: true
actors:
  description: Normalized requested actor rows after module execution or prediction.
  returned: when O(actors) is provided
  type: list
  elements: dict
  sample:
    - user: app
      host: '%'
      role: '%'
      enabled: true
      history: false
objects:
  description: Normalized requested object rows after module execution or prediction.
  returned: when O(objects) is provided
  type: list
  elements: dict
  sample:
    - object_type: TABLE
      object_schema: reporting
      object_name: slow_queries
      enabled: true
      timed: false
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mariadb.plugins.module_utils.mysql import (
    mysql_common_argument_spec,
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
)
from ansible_collections.ansible.mariadb.plugins.module_utils.perf_schema import (
    SECTION_DEFINITIONS,
    ensure_perf_schema_sections_supported,
    plan_section_changes,
)


class MySQLPerfSchema(object):
    def __init__(self, module, cursor):
        self.module = module
        self.cursor = cursor

    def apply(self, params):
        sections = [section for section in SECTION_DEFINITIONS if params.get(section)]
        ensure_perf_schema_sections_supported(self.module, self.cursor, sections)

        result = {
            'changed': False,
            'queries': [],
        }

        for section in sections:
            current_rows = self.get_section_rows(section)
            planned = plan_section_changes(section, params[section], current_rows)
            result['changed'] = result['changed'] or planned['changed']
            result['queries'].extend(query['display'] for query in planned['queries'])
            result[section] = planned['rows']

            if not self.module.check_mode:
                self.execute_queries(planned['queries'])

        if not result['queries']:
            del result['queries']

        return result

    def get_section_rows(self, section):
        definition = SECTION_DEFINITIONS[section]
        fields = ', '.join(definition['db_key_fields'] + definition['db_value_fields'])
        query = 'SELECT %s FROM performance_schema.%s' % (fields, definition['table'])
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def execute_queries(self, queries):
        for query in queries:
            self.cursor.execute(query['sql'], query['params'])
            self.cursor.fetchall()


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        instruments=dict(
            type='list',
            elements='dict',
            options=dict(
                name=dict(type='str', required=True),
                enabled=dict(type='bool', required=True),
                timed=dict(type='bool', required=True),
            ),
        ),
        consumers=dict(
            type='list',
            elements='dict',
            options=dict(
                name=dict(type='str', required=True),
                enabled=dict(type='bool', required=True),
            ),
        ),
        actors=dict(
            type='list',
            elements='dict',
            required_if=[('state', 'present', ('enabled', 'history'))],
            options=dict(
                user=dict(type='str', required=True),
                host=dict(type='str', required=True),
                role=dict(type='str', required=True),
                enabled=dict(type='bool'),
                history=dict(type='bool'),
                state=dict(type='str', choices=['absent', 'present'], default='present'),
            ),
        ),
        objects=dict(
            type='list',
            elements='dict',
            required_if=[('state', 'present', ('enabled', 'timed'))],
            options=dict(
                object_type=dict(type='str', required=True),
                object_schema=dict(type='str', required=True),
                object_name=dict(type='str', required=True),
                enabled=dict(type='bool'),
                timed=dict(type='bool'),
                state=dict(type='str', choices=['absent', 'present'], default='present'),
            ),
        ),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        required_one_of=[('instruments', 'consumers', 'actors', 'objects')],
        supports_check_mode=True,
    )

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    try:
        cursor, db_conn = mysql_connect(
            module,
            module.params['login_user'],
            module.params['login_password'],
            module.params['config_file'],
            module.params['client_cert'],
            module.params['client_key'],
            module.params['ca_cert'],
            connect_timeout=module.params['connect_timeout'],
            check_hostname=module.params['check_hostname'],
            cursor_class='DictCursor',
            autocommit=True,
        )
    except Exception as e:
        module.fail_json(msg='unable to connect to database: %s' % to_native(e))

    executor = MySQLPerfSchema(module, cursor)

    try:
        result = executor.apply(module.params)
    except ValueError as e:
        module.fail_json(msg='invalid performance schema request: %s' % to_native(e))
    except Exception as e:
        module.fail_json(msg=to_native(e))

    module.exit_json(**result)


if __name__ == '__main__':
    main()
