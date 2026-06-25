#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: mysql_clone

short_description: Clone a MySQL instance from a donor server

description:
- Starts a MySQL remote clone operation on the recipient server and waits until the clone reaches a terminal state.
- Validates MySQL Clone plugin prerequisites on the recipient server but does not install or manage the plugin.
- The module is limited to MySQL Clone plugin behavior and fails on MariaDB.

author:
- Ron Gershburg (@rgershbu)

version_added: '5.1.0'

options:
  donor_host:
    description:
    - Hostname or IP address of the donor MySQL server.
    type: str
    required: true
  donor_port:
    description:
    - TCP port of the donor MySQL server.
    type: int
    default: 3306
  donor_user:
    description:
    - User account used by the recipient to connect to the donor for clone.
    type: str
    required: true
  donor_password:
    description:
    - Password used by the recipient to connect to the donor for clone.
    - The password is sent to MySQL as part of the C(CLONE INSTANCE FROM ...) statement.
    type: str
    required: true
  require_ssl:
    description:
    - Whether to append C(REQUIRE SSL) or C(REQUIRE NO SSL) to the clone statement.
    - If omitted, no SSL clause is added and MySQL server defaults apply.
    type: bool
  wait_timeout:
    description:
    - Maximum number of seconds to wait for the recipient to reconnect and the clone to reach a terminal state.
    type: int
    default: 1800
  poll_interval:
    description:
    - Number of seconds to wait between reconnect and status polling attempts.
    type: int
    default: 5

notes:
  - MySQL Clone plugin must already be installed and active on the recipient server.
  - Recipient-side clone variables such as C(clone_valid_donor_list) must be configured before running the module.
  - The module is not idempotent. Running it again starts a new clone operation if MySQL accepts it.
  - In check mode the module validates static prerequisites and reports that clone would be started, but does not execute clone.
  - MariaDB is not supported. Use backup and replication workflows instead.

attributes:
  check_mode:
    support: partial
    details:
      - In check mode the module does not start clone, but it still validates static recipient-side prerequisites.
  idempotent:
    support: partial
    details:
      - The module is not idempotent because each successful invocation starts a new clone operation.

seealso:
  - module: ansible.mysql.mysql_variables
  - module: ansible.mysql.mysql_replication

extends_documentation_fragment:
- ansible.mysql.mysql
'''

EXAMPLES = r'''
- name: Configure recipient donor allow-list separately
  ansible.mysql.mysql_variables:
    variable: clone_valid_donor_list
    value: "192.0.2.10:3306"
    mode: persist

- name: Start clone and wait for completion
  ansible.mysql.mysql_clone:
    donor_host: 192.0.2.10
    donor_port: 3306
    donor_user: clone_user
    donor_password: supersecret
    login_unix_socket: /run/mysqld/mysqld.sock

- name: Preview clone action in check mode
  check_mode: true
  ansible.mysql.mysql_clone:
    donor_host: 192.0.2.10
    donor_user: clone_user
    donor_password: supersecret
    login_unix_socket: /run/mysqld/mysqld.sock
'''

RETURN = r'''
query:
  description: Clone statement executed or predicted, with the password redacted.
  returned: always
  type: str
  sample: "CLONE INSTANCE FROM 'clone_user'@'192.0.2.10':3306 IDENTIFIED BY '********'"
clone_status:
  description: Final row from C(performance_schema.clone_status) for the current or last clone operation.
  returned: on success or on clone failure after status was collected
  type: dict
clone_progress:
  description: Rows from C(performance_schema.clone_progress) collected when the clone reaches a terminal state.
  returned: on success or on clone failure after status was collected
  type: list
  elements: dict
'''

import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.ansible.mysql.plugins.module_utils.mysql import (
    get_server_implementation,
    get_server_version,
    mysql_common_argument_spec,
    mysql_connect,
    mysql_driver,
    mysql_driver_fail_msg,
)
from ansible_collections.ansible.mysql.plugins.module_utils.version import LooseVersion


PLUGIN_QUERY = (
    "SELECT PLUGIN_STATUS AS plugin_status "
    "FROM INFORMATION_SCHEMA.PLUGINS WHERE PLUGIN_NAME = 'clone'"
)
CLONE_STATUS_QUERY = "SELECT * FROM performance_schema.clone_status"
CLONE_PROGRESS_QUERY = "SELECT * FROM performance_schema.clone_progress"
TERMINAL_STATES = frozenset(('Completed', 'Failed'))


def validate_clone_support(module, server_implementation, server_version):
    if server_implementation != 'mysql':
        module.fail_json(msg='MariaDB is not supported by mysql_clone.')

    if LooseVersion(server_version) < LooseVersion('8.0.17'):
        module.fail_json(msg='mysql_clone requires MySQL 8.0.17 or newer.')


def build_clone_query(donor_host, donor_port, donor_user, donor_password, require_ssl=None):
    query = 'CLONE INSTANCE FROM %s@%s:%s IDENTIFIED BY %s'
    params = (donor_user, donor_host, donor_port, donor_password)

    if require_ssl is True:
        query += ' REQUIRE SSL'
    elif require_ssl is False:
        query += ' REQUIRE NO SSL'

    return query, params


def _quote_sql_value(value):
    if isinstance(value, bool):
        return '1' if value else '0'

    if isinstance(value, int):
        return str(value)

    return "'%s'" % str(value).replace("'", "''")


def get_redacted_query(query, params):
    redacted_params = list(params)
    if len(redacted_params) >= 4:
        redacted_params[3] = '********'

    pieces = query.split('%s')
    formatted = []
    for idx, piece in enumerate(pieces[:-1]):
        formatted.append(piece)
        formatted.append(_quote_sql_value(redacted_params[idx]))
    formatted.append(pieces[-1])
    return ''.join(formatted)


def is_terminal_state(state):
    return state in TERMINAL_STATES


def should_wait_after_execute_error(error_message):
    if error_message is None:
        return False

    if 'Restart server failed' in error_message:
        return True

    if error_message.startswith('(3707,'):
        return True

    return False


def _close_connection(cursor, connection):
    try:
        if cursor is not None:
            cursor.close()
    except Exception:
        pass

    try:
        if connection is not None:
            connection.close()
    except Exception:
        pass


def _connect(module):
    return mysql_connect(
        module,
        module.params['login_user'],
        module.params['login_password'],
        module.params['config_file'],
        module.params['client_cert'],
        module.params['client_key'],
        module.params['ca_cert'],
        'mysql',
        cursor_class='DictCursor',
        connect_timeout=module.params['connect_timeout'],
        check_hostname=module.params['check_hostname'],
    )


def ensure_clone_plugin_active(module, cursor):
    cursor.execute(PLUGIN_QUERY)
    result = cursor.fetchone()
    if not result or result.get('plugin_status') != 'ACTIVE':
        module.fail_json(msg='MySQL Clone plugin is not active on the recipient server.')


def validate_donor_allowed(module, cursor, donor_host, donor_port):
    cursor.execute("SHOW GLOBAL VARIABLES LIKE 'clone_valid_donor_list'")
    rows = cursor.fetchall()
    if not rows:
        module.fail_json(msg='clone_valid_donor_list is not available on the recipient server.')

    allowed_value = rows[0].get('Value') or ''
    allowed_donors = [item.strip() for item in allowed_value.split(',') if item.strip()]
    donor = '%s:%s' % (donor_host, donor_port)
    if donor not in allowed_donors:
        module.fail_json(msg='Recipient clone_valid_donor_list must contain %s.' % donor)


def fetch_clone_status(cursor):
    cursor.execute(CLONE_STATUS_QUERY)
    rows = cursor.fetchall()
    if not rows:
        return None
    return dict(rows[0])


def fetch_clone_progress(cursor):
    cursor.execute(CLONE_PROGRESS_QUERY)
    return [dict(row) for row in cursor.fetchall()]


def ensure_clone_not_running(module, status):
    if status and status.get('STATE') == 'In Progress':
        module.fail_json(msg='A clone operation is already in progress on the recipient server.')


def wait_for_clone_completion(module, execute_error=None):
    timeout_at = time.time() + module.params['wait_timeout']
    last_status = None
    last_progress = []
    last_error = None

    while time.time() <= timeout_at:
        cursor = None
        connection = None
        try:
            cursor, connection = _connect(module)
            last_status = fetch_clone_status(cursor)
            last_progress = fetch_clone_progress(cursor)
            if last_status and is_terminal_state(last_status.get('STATE')):
                return last_status, last_progress
        except Exception as exc:
            last_error = to_native(exc)
        finally:
            _close_connection(cursor, connection)

        time.sleep(module.params['poll_interval'])

    if last_status is not None:
        module.fail_json(
            msg='Timed out while waiting for clone to reach a terminal state.',
            clone_status=last_status,
            clone_progress=last_progress,
        )

    if last_error is not None:
        message = 'Timed out while reconnecting to the recipient server: %s' % last_error
        if execute_error:
            message += ' Original clone execution result: %s' % execute_error
        module.fail_json(msg=message)

    module.fail_json(msg='Timed out while waiting for clone status to become available.')


def main():
    argument_spec = mysql_common_argument_spec()
    argument_spec.update(
        donor_host=dict(type='str', required=True),
        donor_port=dict(type='int', default=3306),
        donor_user=dict(type='str', required=True),
        donor_password=dict(type='str', required=True, no_log=True),
        require_ssl=dict(type='bool', default=None),
        wait_timeout=dict(type='int', default=1800),
        poll_interval=dict(type='int', default=5),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    if module.params['donor_port'] < 1 or module.params['donor_port'] > 65535:
        module.fail_json(msg='donor_port must be a valid unix port number (1-65535)')

    if module.params['wait_timeout'] <= 0:
        module.fail_json(msg='wait_timeout must be greater than 0')

    if module.params['poll_interval'] <= 0:
        module.fail_json(msg='poll_interval must be greater than 0')

    if mysql_driver is None:
        module.fail_json(msg=mysql_driver_fail_msg)

    query, params = build_clone_query(
        module.params['donor_host'],
        module.params['donor_port'],
        module.params['donor_user'],
        module.params['donor_password'],
        module.params['require_ssl'],
    )
    redacted_query = get_redacted_query(query, params)

    cursor = None
    connection = None
    try:
        cursor, connection = _connect(module)
        server_implementation = get_server_implementation(cursor)
        server_version = get_server_version(cursor)
        validate_clone_support(module, server_implementation, server_version)
        ensure_clone_plugin_active(module, cursor)
        validate_donor_allowed(module, cursor, module.params['donor_host'], module.params['donor_port'])
        ensure_clone_not_running(module, fetch_clone_status(cursor))

        if module.check_mode:
            module.exit_json(
                changed=True,
                query=redacted_query,
                msg='Clone would be started.',
            )

        execute_error = None
        try:
            cursor.execute(query, params)
        except Exception as exc:
            execute_error = to_native(exc)
            if not should_wait_after_execute_error(execute_error):
                module.fail_json(
                    msg='Clone failed to start. %s' % execute_error,
                    query=redacted_query,
                )
    finally:
        _close_connection(cursor, connection)

    status, progress = wait_for_clone_completion(module, execute_error=execute_error)
    state = status.get('STATE')

    if state == 'Completed':
        module.exit_json(
            changed=True,
            msg='Clone completed successfully.',
            query=redacted_query,
            clone_status=status,
            clone_progress=progress,
        )

    message = 'Clone failed.'
    if status.get('ERROR_MESSAGE'):
        message = '%s %s' % (message, status['ERROR_MESSAGE'])
    elif execute_error:
        message = '%s %s' % (message, execute_error)

    module.fail_json(
        msg=message.strip(),
        query=redacted_query,
        clone_status=status,
        clone_progress=progress,
    )


if __name__ == '__main__':
    main()
