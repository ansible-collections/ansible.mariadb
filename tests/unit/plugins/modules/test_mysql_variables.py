# -*- coding: utf-8 -*-

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import pytest

from ansible_collections.ansible.mysql.plugins.modules.mysql_variables import (
    convert_bool_setting_value_wanted,
)


@pytest.mark.parametrize(
    'value,output',
    [
        (1, 'ON'),
        (0, 'OFF'),
        (2, 2),
        ('on', 'ON'),
        ('off', 'OFF'),
        ('ON', 'ON'),
        ('OFF', 'OFF'),
    ]
)
def test_convert_bool_value(value, output):
    assert convert_bool_setting_value_wanted(value) == output
