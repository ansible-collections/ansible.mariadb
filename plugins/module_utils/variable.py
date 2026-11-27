from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible_collections.ansible.mariadb.plugins.module_utils.database import quote_identifier


def convert_bool(value):
    """Convert supported boolean values to the ON/OFF representation used by MariaDB."""
    if isinstance(value, str):
        value = value.upper()

    if value in ('ON', '1', 1, True):
        return 'ON'
    if value in ('OFF', '0', 0, False):
        return 'OFF'
    return value


def typedvalue(value):
    """Convert values to numbers whenever possible, returning other values unchanged."""
    if isinstance(value, (bool, int, float)):
        return value

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def get_variable(cursor, variable):
    cursor.execute("SHOW GLOBAL VARIABLES WHERE Variable_name = %s", (variable,))
    rows = cursor.fetchall()
    return rows[0][1] if len(rows) == 1 else None


def set_variable(cursor, variable, value):
    query = "SET GLOBAL %s = " % quote_identifier(variable, 'vars')
    cursor.execute(query + "%s", (value,))
