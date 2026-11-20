# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mariadb.plugins.module_utils.command_resolver import (
    CommandResolver,
)


@pytest.mark.parametrize(
    'server_version,command,expected',
    [
        ('10.4.23', 'SHOW MASTER STATUS', 'SHOW MASTER STATUS'),
        ('10.5.1', 'SHOW MASTER STATUS', 'SHOW MASTER STATUS'),
        ('10.5.2', 'SHOW MASTER STATUS', 'SHOW BINLOG STATUS'),
        ('11.8.0', 'SHOW MASTER STATUS', 'SHOW BINLOG STATUS'),
        ('10.4.23', 'SHOW SLAVE STATUS', 'SHOW SLAVE STATUS'),
        ('10.5.1', 'SHOW SLAVE STATUS', 'SHOW REPLICA STATUS'),
        ('10.4.23', 'SHOW SLAVE HOSTS', 'SHOW SLAVE HOSTS'),
        ('10.5.1', 'SHOW SLAVE HOSTS', 'SHOW REPLICA HOSTS'),
    ],
)
def test_resolve_version_specific_commands(server_version, command, expected):
    assert CommandResolver('mariadb', server_version).resolve_command(command) == expected


def test_resolve_command_is_case_insensitive():
    assert CommandResolver('mariadb', '10.5.2').resolve_command('show master STATUS') == 'SHOW BINLOG STATUS'


@pytest.mark.parametrize(
    'command',
    [
        'CHANGE MASTER',
        'MASTER_HOST',
        'MASTER_USER',
        'MASTER_PASSWORD',
        'MASTER_PORT',
        'MASTER_CONNECT_RETRY',
        'MASTER_LOG_FILE',
        'MASTER_LOG_POS',
        'MASTER_DELAY',
        'MASTER_SSL',
        'MASTER_SSL_CA',
        'MASTER_SSL_CAPATH',
        'MASTER_SSL_CERT',
        'MASTER_SSL_KEY',
        'MASTER_SSL_CIPHER',
        'MASTER_SSL_VERIFY_SERVER_CERT',
        'MASTER_AUTO_POSITION',
        'RESET MASTER',
    ],
)
def test_resolve_default_commands(command):
    assert CommandResolver('mariadb', '11.8.0').resolve_command(command) == command


def test_resolve_unsupported_command():
    with pytest.raises(ValueError, match='^Unsupported command: SHOW NOTHING$'):
        CommandResolver('mariadb', '11.8.0').resolve_command('SHOW NOTHING')
