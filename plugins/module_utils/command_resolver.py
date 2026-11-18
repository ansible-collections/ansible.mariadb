# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
from ._version import LooseVersion
__metaclass__ = type


class CommandResolver():
    def __init__(self, server_version):
        self.server_version = LooseVersion(server_version)

    def resolve_command(self, command):
        """
        Resolves the appropriate SQL command based on the server version.

        Parameters:
        command (str): The base SQL command to be resolved (e.g., "SHOW SLAVE HOSTS").

        Returns:
        str: The resolved SQL command suitable for the given server version.

        Raises:
        ValueError: If the command is not supported or recognized.

        Example:
        Given a server version `10.5.2`, and a command `SHOW SLAVE HOSTS`,
        the method will resolve the command based on the following table of versions:

        Table:
            [
                ("mariadb", "default", "SHOW SLAVE HOSTS"),
                ("mariadb", "10.5.1", "SHOW REPLICAS HOSTS"),
            ]

        Example usage:
        >>> resolver = CommandResolver("10.5.2")
        >>> resolver.resolve_command("SHOW SLAVE HOSTS")
        'SHOW REPLICAS'

        In this example, the resolver will iterate through the sorted list and
        find the first version less than or equal to 10.5.2,
        which is 10.5.1, and return the corresponding command.
        """

        # Convert the command to uppercase to ensure case-insensitive lookup
        command = command.upper()

        commands = {
            "SHOW MASTER STATUS": {
                "default": "SHOW MASTER STATUS",
                "10.5.2": "SHOW BINLOG STATUS",
            },
            "SHOW SLAVE STATUS": {
                "default": "SHOW SLAVE STATUS",
                "10.5.1": "SHOW REPLICA STATUS",
            },
            "SHOW SLAVE HOSTS": {
                "default": "SHOW SLAVE HOSTS",
                "10.5.1": "SHOW REPLICA HOSTS",
            },
            "CHANGE MASTER": {
                "default": "CHANGE MASTER",
            },
            "MASTER_HOST": {
                "default": "MASTER_HOST",
            },
            "MASTER_USER": {
                "default": "MASTER_USER",
            },
            "MASTER_PASSWORD": {
                "default": "MASTER_PASSWORD",
            },
            "MASTER_PORT": {
                "default": "MASTER_PORT",
            },
            "MASTER_CONNECT_RETRY": {
                "default": "MASTER_CONNECT_RETRY",
            },
            "MASTER_LOG_FILE": {
                "default": "MASTER_LOG_FILE",
            },
            "MASTER_LOG_POS": {
                "default": "MASTER_LOG_POS",
            },
            "MASTER_DELAY": {
                "default": "MASTER_DELAY",
            },
            "MASTER_SSL": {
                "default": "MASTER_SSL",
            },
            "MASTER_SSL_CA": {
                "default": "MASTER_SSL_CA",
            },
            "MASTER_SSL_CAPATH": {
                "default": "MASTER_SSL_CAPATH",
            },
            "MASTER_SSL_CERT": {
                "default": "MASTER_SSL_CERT",
            },
            "MASTER_SSL_KEY": {
                "default": "MASTER_SSL_KEY",
            },
            "MASTER_SSL_CIPHER": {
                "default": "MASTER_SSL_CIPHER",
            },
            "MASTER_SSL_VERIFY_SERVER_CERT": {
                "default": "MASTER_SSL_VERIFY_SERVER_CERT",
            },
            "MASTER_AUTO_POSITION": {
                "default": "MASTER_AUTO_POSITION",
            },
            "RESET MASTER": {
                "default": "RESET MASTER",
            },
        }

        if command not in commands:
            raise ValueError("Unsupported command: %s" % command)

        cmd_syntaxes = commands[command]
        applicable_versions = [(v, cmd) for v, cmd in cmd_syntaxes.items() if v != 'default']
        applicable_versions.sort(reverse=True, key=lambda x: LooseVersion(x[0]))

        for version, cmd in applicable_versions:
            if self.server_version >= LooseVersion(version):
                return cmd

        return cmd_syntaxes["default"]
