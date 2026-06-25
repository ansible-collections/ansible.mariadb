from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

"""Shared table-driven helpers for Performance Schema setup sections."""


SECTION_DEFINITIONS = {
    'instruments': {
        'table': 'setup_instruments',
        'key_fields': ('name',),
        'db_key_fields': ('NAME',),
        'value_fields': ('enabled', 'timed'),
        'db_value_fields': ('ENABLED', 'TIMED'),
        'allow_insert': False,
        'allow_delete': False,
    },
    'consumers': {
        'table': 'setup_consumers',
        'key_fields': ('name',),
        'db_key_fields': ('NAME',),
        'value_fields': ('enabled',),
        'db_value_fields': ('ENABLED',),
        'allow_insert': False,
        'allow_delete': False,
    },
    'actors': {
        'table': 'setup_actors',
        'key_fields': ('host', 'user', 'role'),
        'db_key_fields': ('HOST', 'USER', 'ROLE'),
        'value_fields': ('enabled', 'history'),
        'db_value_fields': ('ENABLED', 'HISTORY'),
        'allow_insert': True,
        'allow_delete': True,
    },
    'objects': {
        'table': 'setup_objects',
        'key_fields': ('object_type', 'object_schema', 'object_name'),
        'db_key_fields': ('OBJECT_TYPE', 'OBJECT_SCHEMA', 'OBJECT_NAME'),
        'value_fields': ('enabled', 'timed'),
        'db_value_fields': ('ENABLED', 'TIMED'),
        'allow_insert': True,
        'allow_delete': True,
    },
}


def normalize_perf_schema_bool(value):
    if isinstance(value, bool):
        return value

    return str(value).upper() in ('YES', 'ON', 'TRUE', '1')


def normalize_perf_schema_item(section, item):
    definition = SECTION_DEFINITIONS[section]
    normalized = {}

    for field in definition['key_fields']:
        value = item.get(field)
        if value is None:
            raise ValueError("Missing required field '%s' for section '%s'" % (field, section))
        normalized[field] = value

    state = item.get('state', 'present')
    if state not in ('present', 'absent'):
        raise ValueError("state must be 'present' or 'absent'")

    if state == 'absent' and not definition['allow_delete']:
        raise ValueError("Section '%s' does not support state=absent" % section)

    if state == 'present':
        for field in definition['value_fields']:
            value = item.get(field)
            if value is None:
                raise ValueError("Missing required field '%s' for section '%s'" % (field, section))
            normalized[field] = normalize_perf_schema_bool(value)

    if definition['allow_delete']:
        normalized['state'] = state

    return normalized


def normalize_perf_schema_row(section, row):
    definition = SECTION_DEFINITIONS[section]
    normalized = {}

    for field, db_field in zip(definition['key_fields'], definition['db_key_fields']):
        normalized[field] = row[db_field]

    for field, db_field in zip(definition['value_fields'], definition['db_value_fields']):
        normalized[field] = normalize_perf_schema_bool(row[db_field])

    return normalized


def ensure_perf_schema_sections_supported(module, cursor, sections):
    table_names = sorted({SECTION_DEFINITIONS[section]['table'] for section in sections})
    placeholders = ', '.join(['%s'] * len(table_names))
    query = (
        "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = 'performance_schema' AND TABLE_NAME IN (%s)"
    ) % placeholders
    cursor.execute(query, tuple(table_names))
    rows = cursor.fetchall()

    columns_by_table = {}
    for row in rows:
        columns_by_table.setdefault(row['TABLE_NAME'], set()).add(row['COLUMN_NAME'])

    for section in sections:
        definition = SECTION_DEFINITIONS[section]
        expected = set(definition['db_key_fields'] + definition['db_value_fields'])
        actual = columns_by_table.get(definition['table'], set())
        missing = sorted(expected - actual)
        if missing:
            module.fail_json(
                msg=("Performance Schema section '%s' is not supported by the server. "
                     "Missing columns: %s" % (section, ', '.join(missing)))
            )


def plan_section_changes(section, desired_items, current_rows):
    definition = SECTION_DEFINITIONS[section]
    current_by_key = {}

    for row in current_rows:
        normalized = normalize_perf_schema_row(section, row)
        current_by_key[_build_key(definition, normalized)] = normalized

    queries = []
    planned_rows = []

    for raw_item in desired_items:
        item = normalize_perf_schema_item(section, raw_item)
        key = _build_key(definition, item)
        current = current_by_key.get(key)
        state = item.get('state', 'present')

        if state == 'absent':
            if current is not None:
                queries.append(_build_delete_query(definition, item))
            continue

        if current is None:
            if not definition['allow_insert']:
                raise ValueError(
                    "Performance Schema section '%s' does not contain the requested row %s"
                    % (section, dict((field, item[field]) for field in definition['key_fields']))
                )

            queries.append(_build_insert_query(definition, item))
            planned_rows.append(dict((field, item[field]) for field in definition['key_fields'] + definition['value_fields']))
            continue

        updates = {}
        for field in definition['value_fields']:
            if current[field] != item[field]:
                updates[field] = item[field]

        if updates:
            queries.append(_build_update_query(definition, item, updates))

        planned_rows.append(_merge_row(definition, current, item))

    planned_rows.sort(key=lambda row: _build_key(definition, row))

    return {
        'changed': bool(queries),
        'queries': queries,
        'rows': planned_rows,
    }


def _build_key(definition, row):
    return tuple(row[field] for field in definition['key_fields'])


def _merge_row(definition, current, desired):
    merged = {}

    for field in definition['key_fields'] + definition['value_fields']:
        merged[field] = desired.get(field, current.get(field))

    return merged


def _build_update_query(definition, item, updates):
    set_parts = []
    params = []

    for field, db_field in zip(definition['value_fields'], definition['db_value_fields']):
        if field not in updates:
            continue
        set_parts.append('%s = %%s' % db_field)
        params.append(_format_perf_schema_bool(updates[field]))

    where_parts = []
    for field, db_field in zip(definition['key_fields'], definition['db_key_fields']):
        where_parts.append('%s = %%s' % db_field)
        params.append(item[field])

    sql = 'UPDATE performance_schema.%s SET %s WHERE %s' % (
        definition['table'],
        ', '.join(set_parts),
        ' AND '.join(where_parts),
    )

    display = 'UPDATE performance_schema.%s SET %s WHERE %s' % (
        definition['table'],
        ', '.join("%s = %s" % (db_field, _quote_sql_value(_format_perf_schema_bool(updates[field])))
                  for field, db_field in zip(definition['value_fields'], definition['db_value_fields'])
                  if field in updates),
        ' AND '.join("%s = %s" % (db_field, _quote_sql_value(item[field]))
                     for field, db_field in zip(definition['key_fields'], definition['db_key_fields'])),
    )

    return {'sql': sql, 'params': tuple(params), 'display': display}


def _build_insert_query(definition, item):
    fields = definition['db_key_fields'] + definition['db_value_fields']
    params = []

    for field in definition['key_fields']:
        params.append(item[field])

    for field in definition['value_fields']:
        params.append(_format_perf_schema_bool(item[field]))

    sql = 'INSERT INTO performance_schema.%s (%s) VALUES (%s)' % (
        definition['table'],
        ', '.join(fields),
        ', '.join(['%s'] * len(fields)),
    )

    display_values = []
    for field in definition['key_fields']:
        display_values.append(_quote_sql_value(item[field]))
    for field in definition['value_fields']:
        display_values.append(_quote_sql_value(_format_perf_schema_bool(item[field])))

    display = 'INSERT INTO performance_schema.%s (%s) VALUES (%s)' % (
        definition['table'],
        ', '.join(fields),
        ', '.join(display_values),
    )

    return {'sql': sql, 'params': tuple(params), 'display': display}


def _build_delete_query(definition, item):
    params = tuple(item[field] for field in definition['key_fields'])
    where_parts = ['%s = %%s' % db_field for db_field in definition['db_key_fields']]
    sql = 'DELETE FROM performance_schema.%s WHERE %s' % (
        definition['table'],
        ' AND '.join(where_parts),
    )
    display = 'DELETE FROM performance_schema.%s WHERE %s' % (
        definition['table'],
        ' AND '.join("%s = %s" % (db_field, _quote_sql_value(item[field]))
                     for field, db_field in zip(definition['key_fields'], definition['db_key_fields'])),
    )

    return {'sql': sql, 'params': params, 'display': display}


def _format_perf_schema_bool(value):
    return 'YES' if value else 'NO'


def _quote_sql_value(value):
    # This is only for human-readable query output in result['queries'].
    return "'%s'" % str(value).replace("'", "''")
