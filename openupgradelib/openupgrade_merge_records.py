# -*- coding: utf-8 -*-
# Copyright 2018 Tecnativa - Pedro M. Baeza
# Copyright 2018 Opener B.V. - Stefan Rijnhart
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import functools
from psycopg2 import ProgrammingError, IntegrityError
from psycopg2.errorcodes import UNIQUE_VIOLATION
from psycopg2.extensions import AsIs
from .openupgrade import logged_query
from .openupgrade_tools import column_exists, table_exists

logger = logging.getLogger('OpenUpgrade')
logger.setLevel(logging.DEBUG)


def _change_foreign_key_refs(env, model_name, record_ids, target_record_id,
                             exclude_columns):
    # As found on https://stackoverflow.com/questions/1152260
    # /postgres-sql-to-list-table-foreign-keys
    env.cr.execute(
        """ SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = %s and ccu.column_name = 'id'
        """, (env[model_name]._table,))
    for table, column in env.cr.fetchall():
        if (table, column) in exclude_columns:
            continue
        # Try one big swoop first
        try:
            with env.cr.savepoint():
                logged_query(
                    env.cr,
                    """
                    UPDATE %(table)s
                    SET "%(column)s" = %(target_record_id)s
                    WHERE "%(column)s" in %(record_ids)s
                    """, {
                        'table': AsIs(table), 'column': AsIs(column),
                        'record_ids': record_ids,
                        'target_record_id': target_record_id,
                    }, skip_no_result=True)
        except (ProgrammingError, IntegrityError) as error:
            if error.pgcode != UNIQUE_VIOLATION:
                raise
            # Fallback on setting each row separately
            env.cr.execute(
                """ SELECT id FROM %(table)s
                    WHERE "%(column)s" in %(record_ids)s """, {
                        'table': AsIs(table),
                        'column': AsIs(column),
                        'record_ids': record_ids})
            for row in env.cr.fetchall():
                try:
                    with env.cr.savepoint():
                        logged_query(
                            env.cr,
                            """
                            UPDATE %(table)s
                            SET "%(column)s" = %(target_record_id)s
                            WHERE id = %(id)s """, {
                                'id': row[0],
                                'table': AsIs(table), 'column': AsIs(column),
                                'target_record_id': target_record_id})
                except (ProgrammingError, IntegrityError) as error:
                    if error.pgcode != UNIQUE_VIOLATION:
                        raise


def _change_many2one_refs_orm(env, model_name, record_ids, target_record_id,
                              exclude_columns):
    fields = env['ir.model.fields'].search([
        ('ttype', '=', 'many2one'),
        ('relation', '=', model_name),
    ])
    for field in fields:
        try:
            model = env[field.model]
        except KeyError:
            continue
        field_name = field.name
        if (
            not model._auto or not model._fields.get(field_name) or
            not field.store or (model._table, field_name) in exclude_columns
        ):
            continue  # Discard SQL views + invalid fields + non-stored fields
        records = model.search([(field_name, 'in', record_ids)])
        if records:
            records.write({field_name: target_record_id})
            logger.debug(
                "Changed %s record(s) in many2one field '%s' of model '%s'",
                len(records), field_name, field.model,
            )


def _change_many2many_refs_orm(env, model_name, record_ids, target_record_id,
                               exclude_columns):
    fields = env['ir.model.fields'].search([
        ('ttype', '=', 'many2many'),
        ('relation', '=', model_name),
    ])
    for field in fields:
        try:
            model = env[field.model]
        except KeyError:
            continue
        field_name = field.name
        if (not model._auto or not model._fields.get(field_name) or
                not field.store or
                (model._table, field_name) in exclude_columns):
            continue  # Discard SQL views + invalid fields + non-stored fields
        records = model.search([(field_name, 'in', record_ids)])
        if records:
            records.write({
                field_name: (
                    [(3, x) for x in record_ids] + [(4, target_record_id)]
                ),
            })
            logger.debug(
                "Changed %s record(s) in many2many field '%s' of model '%s'",
                len(records), field_name, field.model,
            )


def _change_reference_refs_sql(env, model_name, record_ids, target_record_id,
                               exclude_columns):
    cr = env.cr
    cr.execute("""
        SELECT name, model
        FROM ir_model_fields
        WHERE ttype='reference'
        """, (model_name, ))
    rows = cr.fetchall()
    if ('ir.property', 'value_reference') not in rows:
        rows.append(('ir.property', 'value_reference'))
    for row in rows:
        try:
            model = env[row[0]]
        except KeyError:
            continue
        if not model._auto:  # Discard SQL views
            continue
        table = model._table
        if not table_exists(cr, table):
            continue
        column = row[1]
        if not column_exists(cr, table, column) or (
                (table, column) in exclude_columns):
            continue
        where = ' OR '.join(
            ["%s = '%s,%s'" % (row[1], model_name, x) for x in record_ids]
        )
        logged_query(
            cr, """
            UPDATE %s
            SET %s = %s
            WHERE %s
            """, (
                AsIs(table), AsIs(column),
                '%s,%s' % (model_name, target_record_id), AsIs(where)
            ), skip_no_result=True,
        )


def _change_reference_refs_orm(env, model_name, record_ids, target_record_id,
                               exclude_columns):
    fields = env['ir.model.fields'].search([('ttype', '=', 'reference')])
    fields |= env.ref('base.field_ir_property_value_reference')
    for field in fields:
        try:
            model = env[field.model]
        except KeyError:
            continue
        field_name = field.name
        if (not model._auto or not model._fields.get(field_name) or
                not field.store or
                (model._table, field_name) in exclude_columns):
            continue  # Discard SQL views + invalid fields + non-stored fields
        expr = ['%s,%s' % (model_name, x) for x in record_ids]
        domain = [(field_name, '=', x) for x in expr]
        domain[0:0] = ['|' for x in range(len(domain) - 1)]
        records = model.search(domain)
        if records:
            records.write({
                field_name: '%s,%s' % (model_name, target_record_id),
            })
            logger.debug(
                "Changed %s record(s) in reference field '%s' of model '%s'",
                len(records), field_name, field.model,
            )


def _change_translations_orm(env, model_name, record_ids, target_record_id,
                             exclude_columns):
    if ('ir_translation', 'res_id') in exclude_columns:
        return
    records = env['ir.translation'].search([
        ('type', '=', 'model'),
        ('res_id', 'in', record_ids),
        ('name', 'like', '%s,%%' % model_name)])
    if records:
        records.write({'res_id': target_record_id})
        logger.debug(
            "Changed %s translations of model 'ir.translation'",
            len(records))


def _change_translations_sql(env, model_name, record_ids, target_record_id,
                             exclude_columns):
    if ('ir_translation', 'res_id') in exclude_columns:
        return
    logged_query(
        env.cr,
        """
        UPDATE ir_translation SET res_id = %(target_record_id)s
        WHERE type = 'model' AND res_id in %(record_ids)s
        AND name like %(model_name)s || ',%%'""",
        {
            'target_record_id': target_record_id,
            'record_ids': record_ids,
            'model_name': model_name,
        }, skip_no_result=True)


def _adjust_merged_values_orm(env, model_name, record_ids, target_record_id,
                              field_spec):
    """"This method deals with the values on the records to be merged +
    the target record, performing operations that makes sense on the meaning
    of the model.

    :param field_spec: Dictionary with field names as keys and forced operation
      to perform as values. If a field is not present here, default operation
      will be performed.

      Possible operations by field types:

      * Char, Text and Html fields:
        - 'merge' (default): content is concatenated with an ' | ' as separator
        - other value: content on target record is preserved
      * Integer, Float and Monetary fields:
        - 'sum' (default): Sum all the values of the records.
        - 'avg': Perform the arithmetic average of the values of the records.
        - 'max': Put the maximum of all the values.
        - 'min': Put the minimum of all the values.
        - other value: content on target record is preserved
      * Binary field:
        - any value: content on target record is preserved
      * Boolean field:
        - 'and': Perform a logical AND over all values.
        - 'or': Perform a logical OR over all values.
        - other value (default): content on target record is preserved
      * Date and Datetime fields:
        - 'max': Put the maximum of all the values.
        - 'min': Put the minimum of all the values.
        - other value (default): content on target record is preserved
      * Many2one fields:
        - any value: content on target record is preserved
      * Many2many fields:
        - 'merge' (default): combine all the values
        - other value: content on target record is preserved
      * One2many fields:
        - 'merge' (default): combine all the values
        - other value: content on target record is preserved
      * Reference fields:
        - any value: content on target record is preserved
      * Selection fields:
        - any value: content on target record is preserved
    """
    model = env[model_name]
    fields = model._fields.values()
    all_records = model.browse(record_ids + [target_record_id])
    target_record = model.browse(target_record_id)
    vals = {}
    o2m_changes = 0
    for field in fields:
        if not field.store or field.compute or field.related:
            continue  # don't do anything on these cases
        op = field_spec.get(field.name, False)
        l = all_records.mapped(field.name)
        if field.type in ('char', 'text', 'html'):
            if not op:
                op = 'other' if field.type == 'char' else 'merge'
            if op == 'merge':
                vals[field.name] = ' | '.join(l)
        elif field.type in ('integer', 'float', 'monetary'):
            if not op:
                op = 'other' if field.type == 'integer' else 'sum'
            if op == 'sum':
                vals[field.name] = sum(l)
            elif op == 'avg':
                vals[field.name] = sum(l) / len(l)
            elif op == 'max':
                vals[field.name] = max(l)
            elif op == 'min':
                vals[field.name] = min(l)
        elif field.type == 'boolean':
            op = op or 'other'
            if op == 'and':
                vals[field.name] = functools.reduce(lambda x, y: x & y, l)
            elif op == 'or':
                vals[field.name] = functools.reduce(lambda x, y: x | y, l)
        elif field.type in ('date', 'datetime'):
            op = op or 'other'
            if op == 'max':
                vals[field.name] = max(l)
            elif op == 'min':
                vals[field.name] = min(l)
        elif field.type == 'many2many':
            op = op or 'merge'
            if op == 'merge':
                vals[field.name] = [(4, x.id) for x in l]
        elif field.type == 'one2many':
            op = op or 'merge'
            if op == 'merge':
                o2m_changes += 1
                l.write({field.inverse_name: target_record_id})
    # Curate values that haven't changed
    new_vals = {}
    for f in vals:
        if vals[f] != getattr(target_record, f):
            new_vals[f] = vals[f]
    if new_vals:
        target_record.write(new_vals)
        logger.debug(
            "Write %s value(s) in target record '%s' of model '%s'",
            len(new_vals) + o2m_changes, target_record_id, model_name,
        )


def _change_generic(env, model_name, record_ids, target_record_id,
                    exclude_columns, method='orm'):
    """ Update known generic style res_id/res_model references """
    for model_to_replace, res_id_column, model_column in [
            ('calendar.event', 'res_id', 'res_model'),
            ('ir.attachment', 'res_id', 'res_model'),
            ('mail.activity', 'res_id', 'res_model'),
            ('mail.followers', 'res_id', 'res_model'),
            ('mail.message', 'res_id', 'model'),
            ('rating.rating', 'res_id', 'res_model'),
            ]:
        try:
            model = env[model_to_replace]
        except KeyError:
            continue
        if (model._table, res_id_column) in exclude_columns:
            continue
        if method == 'orm':
            records = model.search([
                (model_column, '=', model_name),
                (res_id_column, 'in', record_ids)])
            if records:
                records.write({res_id_column: target_record_id})
                logger.debug(
                    "Changed %s record(s) of model '%s'",
                    len(records), model_to_replace)
        else:
            logged_query(
                env.cr,
                """ UPDATE %(table)s
                    SET %(res_id_column)s = %(target_record_id)s
                    WHERE %(model_column)s = %(model_name)s
                    AND %(res_id_column)s in %(record_ids)s
                """,
                {
                    'table': AsIs(model._table),
                    'res_id_column': AsIs(res_id_column),
                    'model_column': AsIs(model_column),
                    'model_name': model_name,
                    'target_record_id': target_record_id,
                    'record_ids': record_ids,
                }, skip_no_result=True)


def _delete_records_sql(env, model_name, record_ids):
    logged_query(
        env.cr, "DELETE FROM ir_model_data WHERE model = %s AND id IN %s",
        (env[model_name]._table, tuple(record_ids)),
    )
    logged_query(
        env.cr, "DELETE FROM ir_attachment WHERE res_model = %s AND id IN %s",
        (env[model_name]._table, tuple(record_ids)),
    )
    logged_query(
        env.cr, "DELETE FROM %s WHERE id IN %s",
        (AsIs(env[model_name]._table), tuple(record_ids)),
    )


def _delete_records_orm(env, model_name, record_ids, target_record_id):
    records = env[model_name].browse(record_ids).exists()
    if records:
        records.unlink()
        logger.debug(
            "Deleted %s source record(s) of model '%s'",
            len(record_ids), model_name,
        )


def merge_records(env, model_name, record_ids, target_record_id,
                  field_spec=None, method='orm', delete=True,
                  exclude_columns=None):
    """Merge several records into the target one.

    NOTE: This should be executed in end migration scripts for assuring that
    all the possible relations are loaded and changed. Tested on v11.

    :param env: Environment variable
    :param model_name: Name of the model of the records to merge
    :param record_ids: List of IDS of records that are going to be merged.
    :param target_record_id: ID of the record where the rest records are going
      to be merge in.
    :param field_spec: Dictionary with field names as keys and forced operation
      to perform as values. If a field is not present here, default operation
      will be performed. See _adjust_merged_values_orm method doc for all the
      available operators.
    :param method: Specify how to perform operations. By default or specifying
      'orm', operations will be performed with ORM, maybe slower, but safer, as
      related and computed fields will be recomputed on changes, and all
      constraints will be checked.
    :param delete: If set, the source ids will be unlinked.
    :exclude_columns: list of tuples (table, column) that will be ignored.
    """
    if exclude_columns is None:
        exclude_columns = []
    if field_spec is None:
        field_spec = {}
    if isinstance(record_ids, list):
        record_ids = tuple(record_ids)
    args = (env, model_name, record_ids, target_record_id, exclude_columns)
    args2 = args + (field_spec, )

    _change_generic(*args, method=method)
    if method == 'orm':
        _change_many2one_refs_orm(*args)
        _change_many2many_refs_orm(*args)
        _change_reference_refs_orm(*args)
        _change_translations_orm(*args)
        # TODO: serialized fields
        with env.norecompute():
            _adjust_merged_values_orm(*args2)
        env[model_name].recompute()
        if delete:
            _delete_records_orm(env, model_name, record_ids, target_record_id)
    else:
        _change_foreign_key_refs(*args)
        _change_reference_refs_sql(*args)
        _change_translations_sql(*args)
        # TODO: Adjust values of the merged records through SQL
        if delete:
            _delete_records_sql(env, model_name, record_ids, target_record_id)
