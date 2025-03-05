# -*- coding: utf-8 -*- # pylint: disable=C8202
# Copyright 2018 Tecnativa - Pedro M. Baeza
# Copyright 2018 Opener B.V. - Stefan Rijnhart
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import functools
import logging

from psycopg2 import IntegrityError, ProgrammingError, sql
from psycopg2.errorcodes import UNDEFINED_COLUMN, UNIQUE_VIOLATION
from psycopg2.extensions import AsIs

from .openupgrade import get_model2table, logged_query, version_info
from .openupgrade_tools import column_exists, table_exists

logger = logging.getLogger("OpenUpgrade")
logger.setLevel(logging.DEBUG)


def _change_foreign_key_refs(
    env,
    model_name,
    record_ids,
    target_record_id,
    exclude_columns,
    model_table,
    extra_where=None,
):
    # As found on https://stackoverflow.com/questions/1152260
    # /postgres-sql-to-list-table-foreign-keys
    # Adapted for specific Odoo structures like many2many tables
    env.cr.execute(
        """ SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND ccu.table_name = %s and ccu.column_name = 'id'
        """,
        (model_table,),
    )
    for table, column in env.cr.fetchall():
        if (table, column) in exclude_columns:
            continue
        # Try one big swoop first
        env.cr.execute("SAVEPOINT sp1")  # can't use env.cr.savepoint() in base
        try:
            query = sql.SQL(
                """UPDATE {table}
                SET {column} = %(target_record_id)s
                WHERE {column} in %(record_ids)s"""
            ).format(
                table=sql.Identifier(table),
                column=sql.Identifier(column),
            )
            if extra_where:
                query += sql.SQL(extra_where)
            logged_query(
                env.cr,
                query,
                {
                    "record_ids": tuple(record_ids),
                    "target_record_id": target_record_id,
                },
                skip_no_result=True,
            )
        except (ProgrammingError, IntegrityError) as error:
            env.cr.execute("ROLLBACK TO SAVEPOINT sp1")
            if error.pgcode == UNDEFINED_COLUMN and extra_where:
                # extra_where is introducing a bad column. Ignore this table.
                continue
            elif error.pgcode != UNIQUE_VIOLATION:
                raise
            # Fallback on setting each row separately
            m2m_table = not column_exists(env.cr, table, "id")
            target_column = column if m2m_table else "id"
            env.cr.execute(
                """SELECT %(target_column)s FROM %(table)s
                WHERE "%(column)s" in %(record_ids)s""",
                {
                    "target_column": AsIs(target_column),
                    "table": AsIs(table),
                    "column": AsIs(column),
                    "record_ids": tuple(record_ids),
                },
            )
            for row in list(set([x[0] for x in env.cr.fetchall()])):
                env.cr.execute("SAVEPOINT sp2")
                try:
                    logged_query(
                        env.cr,
                        """UPDATE %(table)s
                        SET "%(column)s" = %(target_record_id)s
                        WHERE %(target_column)s = %(record_id)s""",
                        {
                            "target_column": AsIs(target_column),
                            "table": AsIs(table),
                            "column": AsIs(column),
                            "record_id": row,
                            "target_record_id": target_record_id,
                        },
                    )
                except (ProgrammingError, IntegrityError) as error:
                    env.cr.execute("ROLLBACK TO SAVEPOINT sp2")
                    if error.pgcode != UNIQUE_VIOLATION:
                        raise
                else:
                    env.cr.execute("RELEASE SAVEPOINT sp2")
            if m2m_table:
                # delete remaining values that could not be merged
                logged_query(
                    env.cr,
                    """DELETE FROM %(table)s
                    WHERE "%(column)s" in %(record_ids)s""",
                    {
                        "table": AsIs(table),
                        "column": AsIs(column),
                        "record_ids": tuple(record_ids),
                    },
                    skip_no_result=True,
                )
        else:
            env.cr.execute("RELEASE SAVEPOINT sp1")


def _change_many2one_refs_orm(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    fields = env["ir.model.fields"].search(
        [
            ("ttype", "=", "many2one"),
            ("relation", "=", model_name),
        ]
    )
    for field in fields:
        try:
            model = env[field.model].with_context(active_test=False)
        except KeyError:
            continue
        field_name = field.name
        if (
            not model._auto
            or not model._fields.get(field_name)
            or not field.store
            or (model._table, field_name) in exclude_columns
        ):
            continue  # Discard SQL views + invalid fields + non-stored fields
        records = model.search([(field_name, "in", record_ids)])
        if records:
            records.write({field_name: target_record_id})
            logger.debug(
                "Changed %s record(s) in many2one field '%s' of model '%s'",
                len(records),
                field_name,
                field.model,
            )


def _change_many2many_refs_orm(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    fields = env["ir.model.fields"].search(
        [
            ("ttype", "=", "many2many"),
            ("relation", "=", model_name),
        ]
    )
    for field in fields:
        try:
            model = env[field.model].with_context(active_test=False)
        except KeyError:
            continue
        field_name = field.name
        if (
            not model._auto
            or not model._fields.get(field_name)
            or not field.store
            or (model._table, field_name) in exclude_columns
        ):
            continue  # Discard SQL views + invalid fields + non-stored fields
        records = model.search([(field_name, "in", record_ids)])
        if records:
            records.write(
                {
                    field_name: (
                        [(3, x) for x in record_ids] + [(4, target_record_id)]
                    ),
                }
            )
            logger.debug(
                "Changed %s record(s) in many2many field '%s' of model '%s'",
                len(records),
                field_name,
                field.model,
            )


def _change_reference_refs_sql(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    cr = env.cr
    cr.execute(
        """
        SELECT model, name
        FROM ir_model_fields
        WHERE ttype='reference'
        """
    )
    rows = cr.fetchall()
    if ("ir.property", "value_reference") not in rows:
        rows.append(("ir.property", "value_reference"))
    for row in rows:
        try:
            model = env[row[0]]
            if not model._auto:  # Discard SQL views
                continue
            table = model._table
        except KeyError:
            table = get_model2table(row[0])
        if not table_exists(cr, table):
            continue
        column = row[1]
        if not column_exists(cr, table, column) or ((table, column) in exclude_columns):
            continue
        where = " OR ".join(
            ["%s = '%s,%s'" % (column, model_name, x) for x in record_ids]
        )
        logged_query(
            cr,
            """
            UPDATE %s
            SET %s = %s
            WHERE %s
            """,
            (
                AsIs(table),
                AsIs(column),
                "%s,%s" % (model_name, target_record_id),
                AsIs(where),
            ),
            skip_no_result=True,
        )


def _change_reference_refs_orm(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    fields = env["ir.model.fields"].search([("ttype", "=", "reference")])
    if version_info[0] >= 12:
        fields |= env.ref("base.field_ir_property__value_reference")
    else:
        fields |= env.ref("base.field_ir_property_value_reference")
    for field in fields:
        try:
            model = env[field.model].with_context(active_test=False)
        except KeyError:
            continue
        field_name = field.name
        if (
            not model._auto
            or not model._fields.get(field_name)
            or not field.store
            or (model._table, field_name) in exclude_columns
        ):
            continue  # Discard SQL views + invalid fields + non-stored fields
        expr = ["%s,%s" % (model_name, x) for x in record_ids]
        records = model.search([(field_name, "in", expr)])
        if records:
            records.write(
                {
                    field_name: "%s,%s" % (model_name, target_record_id),
                }
            )
            logger.debug(
                "Changed %s record(s) in reference field '%s' of model '%s'",
                len(records),
                field_name,
                field.model,
            )


def _change_translations_orm(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    if version_info[0] > 15:
        return
    if ("ir_translation", "res_id") in exclude_columns:
        return
    translation_obj = env["ir.translation"]
    groups = translation_obj.read_group(
        [
            ("type", "=", "model"),
            ("res_id", "in", record_ids),
            ("name", "like", "%s,%%" % model_name),
        ],
        ["name", "lang"],
        ["name", "lang"],
        lazy=False,
    )
    for group in groups:
        target_translation = translation_obj.search(
            [
                ("type", "=", "model"),
                ("res_id", "=", target_record_id),
                ("name", "=", group["name"]),
                ("lang", "=", group["lang"]),
            ]
        )
        records = translation_obj.search(group["__domain"])
        if not target_translation and records:
            # There is no target translation, we pick one for being the new one
            records[:1].res_id = target_record_id
            records = records[1:]
        if records:
            records.unlink()
            logger.debug(
                "Deleted %s extra translations for %s (lang = %s).",
                len(records),
                group["name"],
                group["lang"],
            )


def _change_translations_sql(
    env, model_name, record_ids, target_record_id, exclude_columns
):
    if version_info[0] > 15:
        return
    if ("ir_translation", "res_id") in exclude_columns:
        return
    logged_query(
        env.cr,
        """
        UPDATE ir_translation it
        SET res_id = %(target_record_id)s
        FROM (
            SELECT min(it.id) as id, it.name, it.lang
            FROM ir_translation it
            LEFT JOIN ir_translation it2 ON (
                it2.type = it.type AND it2.name = it.name
                AND it2.lang = it.lang AND it2.res_id = %(target_record_id)s)
            WHERE it.type = 'model' AND it.res_id IN %(record_ids)s
                AND it.name like %(model_name)s || ',%%' AND it2.id IS NULL
            GROUP BY it.name, it.lang
        ) AS to_update
        WHERE it.id = to_update.id""",
        {
            "target_record_id": target_record_id,
            "record_ids": tuple(record_ids),
            "model_name": model_name,
        },
        skip_no_result=True,
    )
    logged_query(
        env.cr,
        """
        DELETE FROM ir_translation it
        USING (
            SELECT it.id
            FROM ir_translation it
            WHERE it.type = 'model' AND it.res_id IN %(record_ids)s
                AND it.name like %(model_name)s || ',%%'
        ) AS to_delete
        WHERE it.id = to_delete.id""",
        {
            "target_record_id": target_record_id,
            "record_ids": record_ids,
            "model_name": model_name,
        },
    )


# flake8: noqa: C901
def apply_operations_by_field_type(
    env,
    model_name,
    record_ids,
    target_record_id,
    field_spec,
    field_vals,
    field_type,
    column,
    operation,
    method,
):
    vals = {}
    o2m_changes = 0
    if method == "orm":
        model = env[model_name]
        all_records = model.browse((target_record_id,) + tuple(record_ids))
        if operation == "first_from_origin":
            operation = "first_not_null"
            target_record = model.browse(record_ids[0])
        else:
            target_record = model.browse(target_record_id)
        first_value = getattr(target_record, column)
        field = model._fields[column]
    else:
        if operation == "first_from_origin":
            operation = "first_not_null"
            field_vals.reverse()
        first_value = field_vals[0]
    if field_type in ("char", "text", "html"):
        if not operation:
            operation = "other" if field_type == "char" else "merge"
        if operation == "first_not_null":
            field_vals = [x for x in field_vals if x]
            if field_vals:
                vals[column] = field_vals[0]
        elif operation == "merge":
            _list = filter(lambda x: x, field_vals)
            vals[column] = " | ".join(_list)
    elif field_type in ("jsonb", "serialized"):
        operation = operation or "first_not_null"
        if operation == "first_not_null":
            field_vals.reverse()
            field_val = {}
            for x in field_vals:
                field_val |= x or {}
            if field_val:
                if method == "sql":
                    if field_type == "serialized":
                        import json

                        vals[column] = json.dumps(field_val)
                    elif field_type == "jsonb":
                        from psycopg2.extras import Json

                        vals[column] = Json(field_val)
                else:
                    vals[column] = field_val
    elif field_type in ("integer", "float", "monetary"):
        if operation or field_type != "integer":
            field_vals = [0 if not x else x for x in field_vals]
        if not operation:
            operation = "other" if field_type == "integer" else "sum"
        if operation == "sum":
            vals[column] = sum(field_vals)
        elif operation == "avg":
            vals[column] = sum(field_vals) / len(field_vals)
        elif operation == "max":
            vals[column] = max(field_vals)
        elif operation == "min":
            vals[column] = min(field_vals)
        elif operation == "first_not_null":
            field_vals = [x for x in field_vals if x]
            if field_vals:
                vals[column] = field_vals[0]
    elif field_type == "boolean":
        if operation:
            field_vals = [False if x is None else x for x in field_vals]
        operation = operation or "other"
        if operation == "and":
            vals[column] = functools.reduce(lambda x, y: x & y, field_vals)
        elif operation == "or":
            vals[column] = functools.reduce(lambda x, y: x | y, field_vals)
    elif field_type in ("date", "datetime"):
        if operation:
            field_vals = list(filter(lambda x: x, field_vals))
        operation = field_vals and operation or "other"
        if operation == "max":
            vals[column] = max(field_vals)
        elif operation == "min":
            vals[column] = min(field_vals)
        elif operation == "first_not_null":
            field_vals = [x for x in field_vals if x]
            if field_vals:
                vals[column] = field_vals[0]
    elif field_type == "many2many" and method == "orm":
        operation = operation or "merge"
        if operation == "merge":
            field_vals = filter(lambda x: x is not False, field_vals)
            vals[column] = [(4, x.id) for x in field_vals]
    elif field_type == "one2many" and method == "orm":
        operation = operation or "merge"
        if operation == "merge":
            o2m_changes += 1
            field_vals.write({field.inverse_name: target_record.id})
    elif field_type == "binary":
        operation = operation or "merge"
        if operation == "merge":
            field_vals = [x for x in field_vals if x]
            if not first_value and field_vals:
                vals[column] = field_vals[0]
    elif field_type in ("many2one", "reference"):
        operation = operation or "merge"
        if operation == "merge":
            if method != "orm":
                field_vals = [x for x in field_vals if x]
            if not first_value and field_vals:
                if method == "orm":
                    vals[column] = field_vals[0].id
                else:
                    vals[column] = field_vals[0]
    elif (
        field_type == "many2one_reference"
        and method == "orm"
        and field.model_field in model._fields
    ):
        operation = operation or "merge"
        if operation == "merge":
            if field.model_field in field_spec:
                del field_spec[field.model_field]
            list_model_field = all_records.mapped(field.model_field)
            zip_list = [(x, y) for x, y in zip(field_vals, list_model_field) if x and y]
            if first_value and zip_list:
                vals[column] = zip_list[0][0]
                vals[field.model_field] = zip_list[0][1]
    elif field_type == "selection":
        if operation == "first_not_null":
            field_vals = [x for x in field_vals if x]
            if field_vals:
                vals[column] = field_vals[0]
    if method == "orm":
        return vals, o2m_changes
    else:
        return vals


def _adjust_merged_values_orm(
    env, model_name, record_ids, target_record_id, field_spec, delete=True
):
    """This method deals with the values on the records to be merged +
    the target record, performing operations that make sense on the meaning
    of the model.

    :param: field_spec: Dictionary with field names as keys and forced
      operation to perform as values. If a field is not present here, default
      operation will be performed.
      Note: If you pass 'openupgrade_other_fields': 'preserve' in the dict,
      the fields that are not specified in the dict will not be adjusted.

      Possible operations by field types:

      * Char, Text and Html fields:
        - 'merge' (default for Text and Html): content is concatenated
          with an ' | ' as separator
        - 'first_not_null': Put first not null value.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value (default for Char): content on target record is preserved
      * Integer, Float and Monetary fields:
        - 'sum' (default for Float and Monetary): Sum all the values of
          the records.
        - 'avg': Perform the arithmetic average of the values of the records.
        - 'max': Put the maximum of all the values.
        - 'min': Put the minimum of all the values.
        - 'first_not_null': Put first non-zero value.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value (default for Integer): content on target record
          is preserved
      * Binary field:
        - 'merge' (default): apply first not null value of the records if
        value of target record is null, preserve target value otherwise.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Boolean field:
        - 'and': Perform a logical AND over all values.
        - 'or': Perform a logical OR over all values.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value (default): content on target record is preserved
      * Date and Datetime fields:
        - 'max': Put the maximum of all the values.
        - 'min': Put the minimum of all the values.
        - 'first_not_null': Put first defined Date(time) value.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value (default): content on target record is preserved
      * Many2one fields:
        - 'merge' (default): apply first not null value of the records if
        value of target record is null, preserve target value otherwise.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Many2many fields:
        - 'merge' (default): combine all the values
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * One2many fields:
        - 'merge' (default): combine all the values
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Many2manyReference fields:
        - 'merge' (default): if its model_field is in field_spec,
        delete it from there. Apply first positive (on field and
        corresponding model_field) of the records if value of target record
        is not positive, preserve target value otherwise.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Reference fields:
        - 'merge' (default): apply first not null value of the records if
        value of target record is null, preserve target value otherwise.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Selection fields:
        - any value: content on target record is preserved
        - 'first_from_origin': content from the first origin record is preserved.
        - 'first_not_null': Put first not null value.
      * Serialized fields:
        - 'first_not_null' (default): For each found key, put first not null value.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
      * Translatable (in v16 or greater) fields as 'Jsonb' columns:
        - 'first_not_null' (default): For each found key, put first not null value.
        - 'first_from_origin': content from the first origin record is preserved.
        - other value: content on target record is preserved
    """
    model = env[model_name]
    fields = model._fields.values()
    all_records = model.browse((target_record_id,) + tuple(record_ids))
    target_record = model.browse(target_record_id)
    vals = {}
    o2m_changes = 0
    for field in fields:
        if (
            field_spec.get("openupgrade_other_fields", "") == "preserve"
            and field.name not in field_spec
        ):
            continue
        if not field.store or field.compute or field.related:
            continue  # don't do anything on these cases
        op = field_spec.get(field.name, False)
        if field.type != "reference":
            _list = all_records.mapped(field.name)
        else:
            _list = [x[field.name] for x in all_records if x[field.name]]
        field_vals, field_o2m_changes = apply_operations_by_field_type(
            env,
            model_name,
            record_ids,
            target_record_id,
            field_spec,
            _list,
            field.type if not (version_info[0] > 15 and field.translate) else "jsonb",
            field.name,
            op,
            "orm",
        )
        vals.update(field_vals)
        o2m_changes += field_o2m_changes
    if not vals:
        return
    # Curate values that haven't changed
    new_vals = {}
    for f in vals:
        if model._fields[f].type != "many2many":
            if vals[f] != getattr(target_record, f):
                new_vals[f] = vals[f]
        else:
            if [x[1] for x in vals[f]] not in getattr(target_record, f).ids:
                new_vals[f] = vals[f]
    if delete:
        _delete_records_orm(env, model_name, record_ids, target_record_id)
    if new_vals:
        target_record.write(new_vals)
        logger.debug(
            "Write %s value(s) in target record '%s' of model '%s'",
            len(new_vals) + o2m_changes,
            target_record_id,
            model_name,
        )


def _adjust_merged_values_sql(
    env, model_name, record_ids, target_record_id, model_table, field_spec, delete=True
):
    """This method deals with the values on the records to be merged +
    the target record, performing operations that make sense on the meaning
    of the model.

    :param: field_spec: Dictionary with field names as keys and forced
      operation to perform as values. If a field is not present here, default
      operation will be performed.
      Note: If you pass 'openupgrade_other_fields': 'preserve' in the dict,
      the fields that are not specified in the dict will not be adjusted.

      Possible operations by field types same as _adjust_merged_values_orm.
    """
    if not column_exists(env.cr, model_table, "id"):
        # TODO: handle one2many and many2many
        return
    env.cr.execute(
        """
        SELECT isc.column_name, isc.data_type, imf.ttype
        FROM information_schema.columns isc
        JOIN ir_model_fields imf ON (
            imf.name = isc.column_name AND imf.model = %s)
        WHERE isc.table_name = %s
        """,
        (model_name, model_table),
    )
    dict_column_type = env.cr.fetchall()
    columns = ", ".join([x[0] for x in dict_column_type])
    env.cr.execute(
        """SELECT {columns}
        FROM {table}
        WHERE id IN %(record_ids)s""".format(
            table=model_table,
            columns=columns,
        ),
        {"record_ids": (target_record_id,) + tuple(record_ids)},
    )
    lists = list(zip(*(env.cr.fetchall())))
    new_vals = {}
    vals = {}
    for i, (column, column_type, field_type) in enumerate(dict_column_type):
        if (
            field_spec.get("openupgrade_other_fields", "") == "preserve"
            and column not in field_spec
        ):
            continue
        op = field_spec.get(column, False)
        _list = list(lists[i])
        if column_type == "jsonb":
            field_type = column_type
        if field_type == "serialized":
            import json

            _list = [x if isinstance(x, dict) else json.loads(x) for x in _list]
        field_vals = apply_operations_by_field_type(
            env,
            model_name,
            record_ids,
            target_record_id,
            field_spec,
            _list,
            field_type,
            column,
            op,
            "sql",
        )
        vals.update(field_vals)
    if not vals:
        return
    # Curate values that haven't changed
    env.cr.execute(
        """SELECT {columns}
        FROM {table}
        WHERE id = %(target_record_id)s
        """.format(
            table=model_table, columns=", ".join(list(vals.keys()))
        ),
        {"target_record_id": target_record_id},
    )
    record_vals = env.cr.dictfetchall()
    for column in vals:
        if vals[column] != record_vals[0]:
            new_vals[column] = vals[column]
    if new_vals:
        if delete:
            _delete_records_sql(
                env, model_name, record_ids, target_record_id, model_table=model_table
            )
        ident_dict = {x: sql.Identifier(x) for x in new_vals.keys()}
        query = sql.SQL(
            "UPDATE {table} SET {set_value} WHERE {id} = %(target_record_id)s"
        ).format(
            table=sql.Identifier(model_table),
            id=sql.Identifier("id"),
            set_value=sql.SQL(
                ", ".join(
                    [
                        "{{{field}}} = %({field})s".format(field=x)
                        for x in new_vals.keys()
                    ]
                )
            ).format(**ident_dict),
        )
        new_vals["target_record_id"] = target_record_id
        logged_query(env.cr, query, new_vals)


def _change_generic(
    env,
    model_name,
    record_ids,
    target_record_id,
    exclude_columns,
    method="orm",
    new_model_name=None,
):
    """Update known generic style res_id/res_model references.
    :param env: ORM environment
    :param model_name: Name of the model that have the generic references.
    :param record_ids: List of ids of the records to be changed.
    :param target_record_id: ID of the target record to host the source records
    :param exclude_columns: list of columns to exclude from the update
    :param method: 'orm' or 'sql'
    :param new_model_name: If specified, name of the new model to use in the
      references. This is useful for being used outside the merge records
      feature, for example when replacing one model per another (i.e.:
      account.invoice > account.move).
    """
    for model_to_replace, res_id_column, model_column in [
        ("calendar.event", "res_id", "res_model"),
        ("ir.attachment", "res_id", "res_model"),
        ("mail.activity", "res_id", "res_model"),
        ("mail.followers", "res_id", "res_model"),
        ("mail.message", "res_id", "model"),
        ("rating.rating", "res_id", "res_model"),
    ]:
        try:
            model = env[model_to_replace].with_context(active_test=False)
            table = model._table
        except KeyError:
            if method == "orm":
                continue
            table = get_model2table(model_to_replace)
        if (table, res_id_column) in exclude_columns:
            continue
        if method == "orm":
            if not model._fields.get(model_column) or not model._fields.get(
                res_id_column
            ):
                continue
            records = model.search(
                [(model_column, "=", model_name), (res_id_column, "in", record_ids)]
            )
            if records:
                vals = {res_id_column: target_record_id}
                if new_model_name:
                    vals[model_column] = new_model_name
                if model_to_replace != "mail.followers":
                    records.write(vals)
                else:
                    # We need to avoid duplicated results in this model
                    target_duplicated = model.search(
                        [
                            (model_column, "=", model_name),
                            (res_id_column, "=", target_record_id),
                            ("partner_id", "in", records.mapped("partner_id").ids),
                        ]
                    )
                    dup_partners = target_duplicated.mapped("partner_id")
                    duplicated = records.filtered(
                        lambda x: (x.partner_id in dup_partners)
                    )
                    (records - duplicated).write(vals)
                    duplicated.unlink()
                logger.debug(
                    "Changed %s record(s) of model '%s'", len(records), model_to_replace
                )
        else:
            if not column_exists(env.cr, table, res_id_column) or not column_exists(
                env.cr, table, model_column
            ):
                continue
            format_args = {
                "table": sql.Identifier(table),
                "res_id_column": sql.Identifier(res_id_column),
                "model_column": sql.Identifier(model_column),
            }
            query_args = {
                "model_name": model_name,
                "new_model_name": new_model_name or model_name,
                "target_record_id": target_record_id,
                "record_ids": tuple(record_ids),
            }
            query = sql.SQL(
                "UPDATE {table} SET {res_id_column} = %(target_record_id)s"
            ).format(**format_args)
            if new_model_name:
                query += sql.SQL(", {model_column} = %(new_model_name)s").format(
                    **format_args
                )
            query += sql.SQL(" WHERE {model_column} = %(model_name)s ").format(
                **format_args
            )
            if model_to_replace != "mail.followers":
                query += sql.SQL("AND {res_id_column} in %(record_ids)s").format(
                    **format_args
                )
                logged_query(env.cr, query, query_args, skip_no_result=True)
            else:
                for record_id in record_ids:
                    query_args["record_id"] = record_id
                    query2 = (
                        query
                        + sql.SQL(
                            """AND {res_id_column} = %(record_id)s
                        AND partner_id NOT IN (
                            SELECT partner_id FROM {table}
                            WHERE {res_id_column} = %(target_record_id)s
                                AND {model_column} = %(new_model_name)s
                        )"""
                        ).format(**format_args)
                    )
                    logged_query(
                        env.cr,
                        query2,
                        query_args,
                        skip_no_result=True,
                    )
                # Remove remaining records non updated (that are duplicates)
                logged_query(
                    env.cr,
                    sql.SQL(
                        "DELETE FROM {table} "
                        "WHERE {model_column} = %(model_name)s "
                        "AND {res_id_column} IN %(record_ids)s"
                    ).format(**format_args),
                    query_args,
                    skip_no_result=True,
                )


def _delete_records_sql(
    env, model_name, record_ids, target_record_id, model_table=None
):
    if not model_table:
        try:
            model_table = env[model_name]._table
        except KeyError:
            model_table = get_model2table(model_name)
    logged_query(
        env.cr,
        "DELETE FROM ir_model_data WHERE model = %s AND res_id IN %s",
        (model_name, tuple(record_ids)),
    )
    logged_query(
        env.cr,
        "DELETE FROM ir_attachment WHERE res_model = %s AND res_id IN %s",
        (model_name, tuple(record_ids)),
    )
    logged_query(
        env.cr,
        sql.SQL("DELETE FROM {} WHERE id IN %s").format(sql.Identifier(model_table)),
        (tuple(record_ids),),
    )


def _delete_records_orm(env, model_name, record_ids, target_record_id):
    records = env[model_name].browse(record_ids).exists()
    if records:
        records.unlink()
        logger.debug(
            "Deleted %s source record(s) of model '%s'",
            len(record_ids),
            model_name,
        )


def _check_recurrence(env, model_name, record_ids, target_record_id, model_table=None):
    if not model_table:
        try:
            model_table = env[model_name]._table
        except KeyError:
            model_table = get_model2table(model_name)
    env.cr.execute(
        """
        SELECT tc.table_name, kcu.column_name, COALESCE(imf.column1, 'id')
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        JOIN ir_model_fields AS imf
            ON imf.model = %s AND imf.relation = imf.model AND ((
                imf.name = kcu.column_name AND
                tc.table_name = ccu.table_name) OR (
                imf.column2 = kcu.column_name AND
                tc.table_name = imf.relation_table))
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND ccu.table_name = %s and ccu.column_name = 'id'
        """,
        (model_name, model_table),
    )
    for table, column, origin in env.cr.fetchall():
        query = sql.SQL(
            """SELECT {column} FROM {table}
            WHERE {origin} = %(target_record_id)s"""
        ).format(
            table=sql.Identifier(table),
            column=sql.Identifier(column),
            origin=sql.Identifier(origin),
        )
        env.cr.execute(
            query,
            {
                "target_record_id": target_record_id,
            },
        )
        new_parent_row = env.cr.fetchall()
        if new_parent_row and new_parent_row[0] in record_ids:
            # When we already have recursive hierarchy, doing a
            # merge of a parent into one of their children let the
            # awkward situation where the child points to itself,
            # so we avoid it checking this condition
            logger.info(
                "Couldn't merge %s record(s) of model %s to record_id %s"
                " to avoid recursion with field %s of table %s",
                len(record_ids),
                model_name,
                target_record_id,
                origin,
                table,
            )
            return True
    return False


def merge_records(
    env,
    model_name,
    record_ids,
    target_record_id,
    field_spec=None,
    method="orm",
    delete=True,
    exclude_columns=None,
    model_table=None,
):
    """Merge several records into the target one.

    NOTE: This should be executed in end migration scripts for assuring that
    all the possible relations are loaded and changed. Tested on v10/v11.

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
    :model_table: name of the model table. If not provided, got through ORM.
    """
    if exclude_columns is None:
        exclude_columns = []
    if field_spec is None and method == "orm":
        field_spec = {}
    if isinstance(record_ids, list):
        record_ids = tuple(record_ids)
    args0 = (env, model_name, record_ids, target_record_id)
    args = args0 + (exclude_columns,)
    if target_record_id in record_ids:
        raise Exception(
            "You can't put the target record in the list or records to be merged."
        )
    _change_generic(*args, method=method)  # pylint: disable=E1124
    if method == "orm":
        # Check which records to be merged exist
        record_ids = env[model_name].browse(record_ids).exists().ids
        if not record_ids:
            return
        if _check_recurrence(env, model_name, record_ids, target_record_id):
            return
        _change_many2one_refs_orm(*args)
        _change_many2many_refs_orm(*args)
        _change_reference_refs_orm(*args)
        _change_translations_orm(*args)
        args2 = args0 + (field_spec,) + (delete,)
        # TODO: serialized fields
        with env.norecompute():
            _adjust_merged_values_orm(*args2)
        if version_info[0] > 15:
            env[model_name].flush_model()
        else:
            env[model_name].recompute()
    else:
        # Check which records to be merged exist
        if not model_table:
            try:
                model_table = env[model_name]._table
            except KeyError:
                model_table = get_model2table(model_name)
        env.cr.execute(
            sql.SQL("SELECT id FROM {} WHERE id IN %s").format(
                sql.Identifier(model_table)
            ),
            (tuple(record_ids),),
        )
        record_ids = [x[0] for x in env.cr.fetchall()]
        if not record_ids:
            return
        if _check_recurrence(
            env, model_name, record_ids, target_record_id, model_table=model_table
        ):
            return
        args3 = args + (model_table,)
        _change_foreign_key_refs(*args3)
        _change_reference_refs_sql(*args)
        _change_translations_sql(*args)
        if field_spec is not None:
            args4 = args0 + (model_table,) + (field_spec,) + (delete,)
            _adjust_merged_values_sql(*args4)
        # Ensure that we delete the origin records
        elif delete:
            _delete_records_sql(
                env, model_name, record_ids, target_record_id, model_table=model_table
            )
