#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: mariadb_replication_filter

short_description: Manage MariaDB replication filters

description:
  - This module only supports MariaDB. Use the C(ansible.mysql) collection for MySQL automation.
  - Manage replica-side replication filters declaratively.
  - MariaDB uses C(SET GLOBAL replicate_*) variables.
  - Changes are runtime only and are not persisted across restart by this module.
  - Persist filter settings separately through server configuration if they must survive a restart.

author:
  - Ron Gershburg (@ronger4)

version_added: '5.2.0'

options:
  replicate_do_db:
    description:
      - Databases that should be replicated.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  replicate_ignore_db:
    description:
      - Databases that should be ignored during replication.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  replicate_do_table:
    description:
      - Fully qualified tables that should be replicated.
      - Values must use C(database.table) syntax.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  replicate_ignore_table:
    description:
      - Fully qualified tables that should be ignored during replication.
      - Values must use C(database.table) syntax.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  replicate_wild_do_table:
    description:
      - Wildcard table patterns that should be replicated.
      - Values must use C(database.table) syntax with C(%) and C(_) wildcards.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  replicate_wild_ignore_table:
    description:
      - Wildcard table patterns that should be ignored during replication.
      - Values must use C(database.table) syntax with C(%) and C(_) wildcards.
      - Provide an empty list to clear the filter.
    type: list
    elements: str
  connection_name:
    description:
      - MariaDB replication connection name.
      - Supported only for MariaDB multi-source replication.
    type: str

notes:
  - Compatible with MariaDB.
  - At least one replication filter option must be provided.
  - Unspecified filters are left unchanged.

attributes:
  check_mode:
    support: full
  idempotent:
    support: full

extends_documentation_fragment:
  - ansible.mariadb.connect
'''

EXAMPLES = r'''
- name: Ignore one database on a MariaDB replica
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    replicate_ignore_db:
      - audit

- name: Replicate selected tables on a MariaDB replica
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    replicate_do_table:
      - app.orders
      - reporting.summary

- name: Set wildcard filters on a MariaDB replica
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    replicate_wild_do_table:
      - app.%
      - reporting.sales_%
    replicate_wild_ignore_table:
      - archive.old_%
      - tmp.%

- name: Set multiple MariaDB filters in one task
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    replicate_do_db:
      - app
    replicate_ignore_table:
      - archive.events

- name: Set one named MariaDB replication filter
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    connection_name: analytics
    replicate_do_db:
      - reporting

- name: Clear one MariaDB wildcard filter
  ansible.mariadb.mariadb_replication_filter:
    login_unix_socket: /run/mysqld/mysqld.sock
    replicate_wild_ignore_table: []
'''

RETURN = r'''
queries:
  description: Executed SQL statements or predicted SQL statements in check mode.
  returned: always
  type: list
  elements: str
  sample:
    - SET GLOBAL `replicate_do_db` = 'app,reporting'
filters:
  description: Effective normalized filter state after execution or prediction.
  returned: always
  type: dict
  contains:
    replicate_do_db:
      description: Databases that should be replicated.
      returned: always
      type: list
      elements: str
    replicate_ignore_db:
      description: Databases that should be ignored during replication.
      returned: always
      type: list
      elements: str
    replicate_do_table:
      description: Fully qualified tables that should be replicated.
      returned: always
      type: list
      elements: str
    replicate_ignore_table:
      description: Fully qualified tables that should be ignored during replication.
      returned: always
      type: list
      elements: str
    replicate_wild_do_table:
      description: Wildcard table patterns that should be replicated.
      returned: always
      type: list
      elements: str
    replicate_wild_ignore_table:
      description: Wildcard table patterns that should be ignored during replication.
      returned: always
      type: list
      elements: str
  sample:
    replicate_do_db:
      - app
      - reporting
    replicate_ignore_db: []
    replicate_do_table: []
    replicate_ignore_table: []
    replicate_wild_do_table: []
    replicate_wild_ignore_table: []
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mariadb.plugins.module_utils.database import check_input, quote_identifier
from ansible_collections.ansible.mariadb.plugins.module_utils.connect import (
    get_server_version,
    common_argument_spec,
    connect,
    driver,
    driver_fail_msg,
)
from ansible_collections.ansible.mariadb.plugins.module_utils.version import LooseVersion


FILTER_VALUE_KINDS = {
    'replicate_do_db': 'database',
    'replicate_ignore_db': 'database',
    'replicate_do_table': 'table',
    'replicate_ignore_table': 'table',
    'replicate_wild_do_table': 'pattern',
    'replicate_wild_ignore_table': 'pattern',
}


def normalize_filter_values(values):
    normalized = []

    for value in values:
        value = value.strip()
        if not value:
            continue
        normalized.append(value)

    return sorted(set(normalized))


def normalize_filter_variables(variables):
    filters = _empty_filters()

    for param in FILTER_VALUE_KINDS:
        raw_value = variables.get(param, '')
        filters[param] = normalize_filter_values(_split_filter_rule(raw_value))

    return filters


def plan_filter_changes(desired_filters, current_filters, query_builder):
    planned_filters = dict((name, list(values)) for name, values in current_filters.items())
    queries = []

    for param, desired_values in desired_filters.items():
        if desired_values is None:
            continue

        normalized_values = normalize_filter_values(desired_values)
        planned_filters[param] = normalized_values

        if current_filters.get(param, []) != normalized_values:
            queries.append(query_builder(param, normalized_values))

    return {
        'changed': bool(queries),
        'queries': queries,
        'filters': planned_filters,
    }


def build_filter_query(param, values):
    value = ','.join(normalize_filter_values(values))
    identifier = quote_identifier(param, 'vars')
    query = 'SET GLOBAL %s = %%s' % identifier

    return {
        'sql': query,
        'params': (value,),
        'display': 'SET GLOBAL %s = %s' % (identifier, _quote_sql_string(value)),
    }


def _empty_filters():
    return dict((name, []) for name in FILTER_VALUE_KINDS)


def _split_filter_rule(value):
    if not value:
        return []

    return [item.strip() for item in value.split(',')]


def _quote_sql_string(value):
    return "'%s'" % value.replace('\\', '\\\\').replace("'", "''")


def _uses_database_table_syntax(value):
    database_name, separator, table_name = value.partition('.')
    return bool(separator and database_name and table_name and '.' not in table_name)


def supports_connection_name(server_version):
    return LooseVersion(server_version) >= LooseVersion('10.0.1')


def get_filter_values(module, cursor, server_version, connection_name=''):
    if connection_name and not supports_connection_name(server_version):
        module.fail_json(msg='connection_name requires MariaDB 10.0.1 or newer')

    if connection_name:
        replica_term = 'REPLICA' if LooseVersion(server_version) >= LooseVersion('10.5.1') else 'SLAVE'
        cursor.execute('SHOW %s %s STATUS' % (replica_term, _quote_sql_string(connection_name)))
        rows = cursor.fetchall()
        if rows:
            row = rows[0]
            return {
                'replicate_do_db': row.get('Replicate_Do_DB', ''),
                'replicate_ignore_db': row.get('Replicate_Ignore_DB', ''),
                'replicate_do_table': row.get('Replicate_Do_Table', ''),
                'replicate_ignore_table': row.get('Replicate_Ignore_Table', ''),
                'replicate_wild_do_table': row.get('Replicate_Wild_Do_Table', ''),
                'replicate_wild_ignore_table': row.get('Replicate_Wild_Ignore_Table', ''),
            }
        return dict((param, '') for param in FILTER_VALUE_KINDS)

    variables = {}
    for param in FILTER_VALUE_KINDS:
        cursor.execute('SELECT @@GLOBAL.%s AS Value' % param)
        rows = cursor.fetchall()
        variables[param] = _extract_variable_value(rows)

    return variables


def _extract_variable_value(rows):
    if not rows:
        return ''

    row = rows[0]
    if isinstance(row, dict):
        return row.get('Value', row.get('VALUE', ''))

    if len(row) == 1:
        return row[0]

    return row[1]


def apply_filters(module, cursor, server_version, desired_filters, connection_name=''):
    validate_filters(module, desired_filters)
    check_input(module, connection_name)

    planned = plan_filter_changes(
        desired_filters,
        normalize_filter_variables(get_filter_values(
            module,
            cursor,
            server_version,
            connection_name=connection_name,
        )),
        build_filter_query,
    )

    if not module.check_mode:
        execute_queries(cursor, planned['queries'], connection_name=connection_name)

    return {
        'changed': planned['changed'],
        'queries': [query['display'] for query in planned['queries']],
        'filters': planned['filters'],
    }


def execute_queries(cursor, queries, connection_name=''):
    if connection_name:
        cursor.execute('SET @@default_master_connection = %s', (connection_name,))
        cursor.fetchall()

    try:
        for query in queries:
            cursor.execute(query['sql'], query['params'])
            cursor.fetchall()
    finally:
        if connection_name:
            cursor.execute('SET @@default_master_connection = %s', ('',))
            cursor.fetchall()


def validate_filters(module, desired_filters):
    for param, values in desired_filters.items():
        if values is None:
            continue
        check_input(module, values)
        values_with_commas = [value for value in values if ',' in value]
        if values_with_commas:
            module.fail_json(
                msg='replication filter values cannot contain commas: %s' % ', '.join(values_with_commas)
            )
        if FILTER_VALUE_KINDS[param] in ('table', 'pattern'):
            invalid_values = [value for value in values if not _uses_database_table_syntax(value)]
            if invalid_values:
                module.fail_json(
                    msg='%s values must use database.table syntax: %s' % (param, ', '.join(invalid_values))
                )


def main():
    argument_spec = common_argument_spec()
    for name in FILTER_VALUE_KINDS:
        argument_spec[name] = dict(type='list', elements='str')

    argument_spec['connection_name'] = dict(type='str')

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    if driver is None:
        module.fail_json(msg=driver_fail_msg)

    desired_filters = dict((name, module.params[name]) for name in FILTER_VALUE_KINDS)
    if not any(values is not None for values in desired_filters.values()):
        module.fail_json(msg='at least one replication filter option must be provided')

    connect_timeout = module.params['connect_timeout']
    login_user = module.params['login_user']
    login_password = module.params['login_password']
    ssl_cert = module.params['client_cert']
    ssl_key = module.params['client_key']
    ssl_ca = module.params['ca_cert']
    check_hostname = module.params['check_hostname']
    config_file = module.params['config_file']

    try:
        cursor, _db_conn = connect(
            module,
            login_user,
            login_password,
            config_file,
            ssl_cert,
            ssl_key,
            ssl_ca,
            None,
            cursor_class='DictCursor',
            connect_timeout=connect_timeout,
            check_hostname=check_hostname,
        )
    except Exception as e:
        module.fail_json(
            msg=(
                "unable to connect to database, check login_user and "
                "login_password are correct or %s has the credentials. "
                "Exception message: %s" % (config_file, to_native(e))
            )
        )

    try:
        module.exit_json(
            **apply_filters(
                module,
                cursor,
                get_server_version(cursor),
                desired_filters,
                connection_name=module.params['connection_name'],
            )
        )
    except ValueError as e:
        module.fail_json(msg='invalid replication filter request: %s' % to_native(e))


if __name__ == '__main__':
    main()
