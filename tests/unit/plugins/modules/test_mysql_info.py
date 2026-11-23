# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock

from ansible_collections.ansible.mariadb.plugins.modules.mariadb_info import MySQL_Info


@pytest.mark.parametrize(
    'suffix,cursor_output,server_implementation,server_version',
    [
        ('mariadb', '10.5.0-mariadb', 'mariadb', '10.5.0'),
    ]
)
def test_get_info_suffix(suffix, cursor_output, server_implementation, server_version):
    def __cursor_return_value(input_parameter):
        if input_parameter == "SHOW GLOBAL VARIABLES":
            cursor.fetchall.return_value = [{"Variable_name": "version", "Value": cursor_output}]
        else:
            cursor.fetchall.return_value = MagicMock()

    cursor = MagicMock()
    cursor.execute.side_effect = __cursor_return_value

    info = MySQL_Info(MagicMock(), cursor, server_implementation, server_version)

    assert info.get_info([], [], False)['version']['suffix'] == suffix
