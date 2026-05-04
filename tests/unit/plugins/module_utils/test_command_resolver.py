# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mysql.plugins.module_utils.command_resolver import (
    CommandResolver,
)


@pytest.mark.parametrize(
    'server_implementation,server_version,command,expected_output,expected_exception,expected_message',
    [
        ('mysql', '1.0.0', 'SHOW NOTHING', '', ValueError, 'Unsupported command: SHOW NOTHING'),
        ('mysql', '8.0.20', 'SHOW MASTER STATUS', 'SHOW MASTER STATUS', None, None),  # Case insensitive
        ('mysql', '8.0.20', 'show master status', 'SHOW MASTER STATUS', None, None),  # Case insensitive
        ('mysql', '8.0.20', 'SHOW master STATUS', 'SHOW MASTER STATUS', None, None),  # Case insensitive
        ('mysql', '8.2.0', 'SHOW MASTER STATUS', 'SHOW BINARY LOG STATUS', None, None),
        ('mysql', '9.0.0', 'SHOW MASTER STATUS', 'SHOW BINARY LOG STATUS', None, None),
        ('mariadb', '10.4.23', 'SHOW MASTER STATUS', 'SHOW MASTER STATUS', None, None),  # Default
        ('mariadb', '10.5.1', 'SHOW MASTER STATUS', 'SHOW MASTER STATUS', None, None),   # Default
        ('mariadb', '10.5.2', 'SHOW MASTER STATUS', 'SHOW BINLOG STATUS', None, None),
        ('mariadb', '10.6.17', 'SHOW MASTER STATUS', 'SHOW BINLOG STATUS', None, None),
        ('mysql', '8.4.1', 'CHANGE MASTER', 'CHANGE REPLICATION SOURCE', None, None),
    ]
)
def test_resolve_command(server_implementation, server_version, command, expected_output, expected_exception, expected_message):
    """
    Tests that the CommandResolver method resolve_command return the correct query.
    """
    resolver = CommandResolver(server_implementation, server_version)
    if expected_exception:
        with pytest.raises(expected_exception) as excinfo:
            resolver.resolve_command(command)
        assert str(excinfo.value) == expected_message
    else:
        assert resolver.resolve_command(command) == expected_output
