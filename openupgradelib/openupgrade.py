# -*- coding: utf-8 -*-
# Copyright 2011-2020 Therp BV <https://therp.nl>.
# Copyright 2016-2020 Tecnativa - Pedro M. Baeza.
# Copyright Odoo Community Association (OCA)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import sys
import os
import inspect
import uuid
import logging as _logging_module
from datetime import datetime
from functools import wraps
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
from contextlib import contextmanager
try:
    from psycopg2 import errorcodes, ProgrammingError, IntegrityError
except ImportError:
    from psycopg2cffi import errorcodes, ProgrammingError, IntegrityError
try:
    from contextlib import ExitStack
except ImportError:

    # we're on python 2.x, reimplement what we use of ExitStack
    class ExitStack:
        def __init__(self):
            self._cms = []

        def enter_context(self, cm):
            self._cms.append(cm)
            cm.__enter__()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            while self._cms:
                self._cms.pop().__exit__(exc_type, exc_value, traceback)

from psycopg2 import sql
from psycopg2.extensions import AsIs
from lxml import etree
from . import openupgrade_tools

core = None
# The order matters here. We can import odoo in 9.0, but then we get odoo.py
try:  # >= 10.0
    import odoo as core
    from odoo.modules import registry
except ImportError:  # < 10.0
    import openerp as core
    from openerp.modules import registry
if hasattr(core, 'release'):
    release = core.release
else:
    import release

Many2many = False
One2many = False
one2many = False
many2many = False
except_orm = False
UserError = False

if not hasattr(release, 'version_info'):
    version_info = tuple(map(int, release.version.split('.')))
else:
    version_info = release.version_info

if version_info[0] > 6 or version_info[0:2] == (6, 1):
    tools = core.tools
    SUPERUSER_ID = core.SUPERUSER_ID

    if hasattr(core, 'osv') and hasattr(core.osv, 'fields'):
        except_orm = core.osv.orm.except_orm
        many2many = core.osv.fields.many2many
        one2many = core.osv.fields.one2many

    if version_info[0] >= 7:
        plaintext2html = tools.mail.plaintext2html
    if version_info[0] >= 8:
        Many2many = core.fields.Many2many
        One2many = core.fields.One2many
        try:  # version 10
            from odoo.exceptions import UserError
        except ImportError:  # version 8 and 9
            from openerp.exceptions import Warning as UserError
    if version_info[0] < 12:
        yaml_import = tools.yaml_import
else:
    # version < 6.1
    import tools
    SUPERUSER_ID = 1
    from tools.yaml_import import yaml_import
    from osv.osv import except_osv as except_orm
    from osv.fields import many2many, one2many


def do_raise(error):
    if UserError:
        raise UserError(error)
    raise except_orm('Error', error)


if sys.version_info[0] == 3:
    unicode = str

if version_info[0] > 7:
    api = core.api
else:
    api = False

# Setting the target version as an environment variable allows OpenUpgrade
# to skip methods that are called in every version but really only need to
# run in the target version. Make the target version available to OpenUpgrade
# with `export OPENUPGRADE_TARGET_VERSION=13.0` (when migrating up to 13.0)
target_version = os.environ.get("OPENUPGRADE_TARGET_VERSION")
if target_version:
    is_target_version = version_info[0] == int(float(target_version))


# The server log level has not been set at this point
# so to log at loglevel debug we need to set it
# manually here. As a consequence, DEBUG messages from
# this file are always logged
logger = _logging_module.getLogger('OpenUpgrade')
logger.setLevel(_logging_module.DEBUG)

__all__ = [
    'migrate',
    'logging',
    'load_data',
    'add_fields',
    'copy_columns',
    'copy_fields_multilang',
    'remove_tables_fks',
    'rename_columns',
    'rename_fields',
    'rename_tables',
    'rename_models',
    'rename_xmlids',
    'add_xmlid',
    'chunked',
    'drop_columns',
    'delete_model_workflow',
    'update_field_multilang',
    'update_workflow_workitems',
    'warn_possible_dataloss',
    'set_defaults',
    'logged_query',
    'column_exists',
    'table_exists',
    'update_module_moved_fields',
    'update_module_names',
    'add_ir_model_fields',
    'get_legacy_name',
    'm2o_to_x2m',
    'float_to_integer',
    'message',
    'check_values_selection_field',
    'move_field_m2o',
    'convert_field_to_html',
    'map_values',
    'deactivate_workflow_transitions',
    'reactivate_workflow_transitions',
    'date_to_datetime_tz',
    'lift_constraints',
    'rename_property',
    'delete_record_translations',
    'disable_invalid_filters',
    'safe_unlink',
    'delete_records_safely_by_xml_id',
    'set_xml_ids_noupdate_value',
    'convert_to_company_dependent',
    'cow_templates_mark_if_equal_to_upstream',
    'cow_templates_replicate_upstream',
]


@contextmanager
def allow_pgcodes(cr, *codes):
    """Context manager that will omit specified error codes.

    E.g., suppose you expect a migration to produce unique constraint
    violations and you want to ignore them. Then you could just do::

        with allow_pgcodes(cr, psycopg2.errorcodes.UNIQUE_VIOLATION):
            cr.execute("INSERT INTO me (name) SELECT name FROM you")

    .. warning::
        **All** sentences inside this context will be rolled back if **a single
        error** is raised, so the above example would insert **nothing** if a
        single row violates a unique constraint.

        This would ignore duplicate files but insert the others::

            cr.execute("SELECT name FROM you")
            for row in cr.fetchall():
                with allow_pgcodes(cr, psycopg2.errorcodes.UNIQUE_VIOLATION):
                    cr.execute("INSERT INTO me (name) VALUES (%s)", row[0])

    :param *str codes:
        Undefined amount of error codes found in :mod:`psycopg2.errorcodes`
        that are allowed. Codes can have either 2 characters (indicating an
        error class) or 5 (indicating a concrete error). Any other errors
        will be raised.
    """
    try:
        with cr.savepoint():
            with core.tools.mute_logger('odoo.sql_db'):
                yield
    except (ProgrammingError, IntegrityError) as error:
        msg = "Code: {code}. Class: {class_}. Error: {error}.".format(
            code=error.pgcode,
            class_=errorcodes.lookup(error.pgcode[:2]),
            error=errorcodes.lookup(error.pgcode))
        if error.pgcode in codes or error.pgcode[:2] in codes:
            logger.info(msg)
        else:
            logger.exception(msg)
            raise


def check_values_selection_field(cr, table_name, field_name, allowed_values):
    """
        check if the field selection 'field_name' of the table 'table_name'
        has only the values 'allowed_values'.
        If not return False and log an error.
        If yes, return True.

    .. versionadded:: 8.0
    """
    res = True
    cr.execute("SELECT %s, count(*) FROM %s GROUP BY %s;" %
               (field_name, table_name, field_name))
    for row in cr.fetchall():
        if row[0] not in allowed_values:
            logger.error(
                "Invalid value '%s' in the table '%s' "
                "for the field '%s'. (%s rows).",
                row[0], table_name, field_name, row[1])
            res = False
    return res


def load_data(cr, module_name, filename, idref=None, mode='init'):
    """
    Load an xml, csv or yml data file from your post script. The usual case for
    this is the
    occurrence of newly added essential or useful data in the module that is
    marked with "noupdate='1'" and without "forcecreate='1'" so that it will
    not be loaded by the usual upgrade mechanism. Leaving the 'mode' argument
    to its default 'init' will load the data from your migration script.

    Theoretically, you could simply load a stock file from the module, but be
    careful not to reinitialize any data that could have been customized.
    Preferably, select only the newly added items. Copy these to a file
    in your migrations directory and load that file.
    Leave it to the user to actually delete existing resources that are
    marked with 'noupdate' (other named items will be deleted
    automatically).


    :param module_name: the name of the module
    :param filename: the path to the filename, relative to the module \
    directory. This may also be the module directory relative to --upgrade-path
    :param idref: optional hash with ?id mapping cache?
    :param mode:
        one of 'init', 'update', 'demo', 'init_no_create'.
        Always use 'init' for adding new items from files that are marked with
        'noupdate'. Defaults to 'init'.

        'init_no_create' is a hack to load data for records which have
        forcecreate=False set. As those records won't be recreated during the
        update, standard Odoo would recreate the record if it was deleted,
        but this will fail in cases where there are required fields to be
        filled which are not contained in the data file.
    """

    if idref is None:
        idref = {}
    logger.info('%s: loading %s' % (module_name, filename))
    _, ext = os.path.splitext(filename)
    pathname = os.path.join(module_name, filename)

    try:
        fp = tools.file_open(pathname)
    except OSError:
        if tools.config.get('upgrade_path'):
            pathname = os.path.join(
                tools.config['upgrade_path'], module_name, filename)
            fp = open(pathname)
        else:
            raise

    try:
        if ext == '.csv':
            noupdate = True
            tools.convert_csv_import(
                cr, module_name, pathname, fp.read(), idref, mode, noupdate)
        elif ext == '.yml':
            yaml_import(cr, module_name, fp, None, idref=idref, mode=mode)
        elif mode == 'init_no_create':
            for fp2 in _get_existing_records(cr, fp, module_name):
                tools.convert_xml_import(
                    cr, module_name, fp2, idref, mode='init',
                )
        else:
            tools.convert_xml_import(cr, module_name, fp, idref, mode=mode)
    finally:
        fp.close()


def _get_existing_records(cr, fp, module_name):
    """yield file like objects per 'leaf' node in the xml file that exists.
    This is for not trying to create a record with partial data in case the
    record was removed in the database."""
    def yield_element(node, path=None):
        if node.tag not in ['openerp', 'odoo', 'data']:
            if node.tag == 'record':
                xmlid = node.attrib['id']
                if '.' not in xmlid:
                    module = module_name
                else:
                    module, xmlid = xmlid.split('.', 1)
                cr.execute(
                    'select id from ir_model_data where module=%s and name=%s',
                    (module, xmlid)
                )
                if not cr.rowcount:
                    return
            result = StringIO(etree.tostring(path, encoding='unicode'))
            result.name = None
            yield result
        else:
            for child in node:
                for value in yield_element(
                        child,
                        etree.SubElement(path, node.tag, node.attrib)
                        if path else etree.Element(node.tag, node.attrib)
                ):
                    yield value
    return yield_element(etree.parse(fp).getroot())


# for backwards compatibility
load_xml = load_data
table_exists = openupgrade_tools.table_exists
column_exists = openupgrade_tools.column_exists


def copy_columns(cr, column_spec):
    """
    Copy table columns. Typically called in the pre script.

    :param column_spec: a hash with table keys, with lists of tuples as
        values. Tuples consist of (old_name, new_name, type). Use None for
        new_name to trigger a conversion of old_name using get_legacy_name()
        Use None for type to use type of old field.
        Make sure to quote properly, if your column name coincides with a
        SQL directive. eg. '"column"'

    .. versionadded:: 8.0
    """
    for table_name in column_spec.keys():
        for (old, new, field_type) in column_spec[table_name]:
            if new is None:
                new = get_legacy_name(old)
            if field_type is None:
                cr.execute("""
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_name=%s
                        AND column_name = %s;
                    """, (table_name, old))
                field_type = cr.fetchone()[0]
            logged_query(cr, """
                ALTER TABLE %(table_name)s
                ADD COLUMN %(new)s %(field_type)s;
                UPDATE %(table_name)s SET %(new)s=%(old)s;
                """ % {
                'table_name': table_name,
                'old': old,
                'field_type': field_type,
                'new': new,
            })


def copy_fields_multilang(cr, destination_model, destination_table,
                          destination_columns, relation_column,
                          source_model=None, source_table=None,
                          source_columns=None, translations_only=False):
    """Copy field contents including translations.

    :param str destination_model:
        Name of the destination model where the data will be copied to.

    :param str destination_table:
        Name of the destination table where the data will be copied to.
        It must be ``env[destination_model]._table``.

    :param list destination_columns:
        List of column names in the ``destination_table`` that will
        receive the copied data.

    :param str relation_column:
        Name of a column in ``destination_table`` which points to IDs in
        ``source_table``. An ``INNER JOIN`` will be done to update the
        destination records with their corresponding source records only.
        Records where this column ``NULL`` will be skipped.

    :param str source_model:
        Name of the source model where the data will be copied from.
        If empty, it will default to ``destination_table``.

    :param str source_table:
        Name of the source table where the data will be copied from.
        If empty, it will default to ``destination_table``.
        It must be ``env[source_model]._table``.

    :param list source_columns:
        List of column names in the ``source_table`` that will
        provide the copied data.
        If empty, it will default to ``destination_columns``.

    :param bool translations_only:
        If ``True``, it will only handle transferring translations. Won't
        copy the raw field from ``source_table``.

    .. versionadded:: 12.0
    """
    if source_model is None:
        source_model = destination_model
    if source_table is None:
        source_table = destination_table
    if source_columns is None:
        source_columns = destination_columns
    cols_len = len(destination_columns)
    assert len(source_columns) == cols_len > 0
    # Basic copy
    if not translations_only:
        query = sql.SQL("""
            UPDATE {dst_t} AS dt
            SET {set_part}
            FROM {src_t} AS st
            WHERE dt.{rel_col} = st.id
        """).format(
            dst_t=sql.Identifier(destination_table),
            set_part=sql.SQL(", ").join(
                sql.SQL("{} = st.{}").format(
                    sql.Identifier(dest_col),
                    sql.Identifier(src_col))
                for (dest_col, src_col)
                in zip(destination_columns, source_columns)),
            src_t=sql.Identifier(source_table),
            rel_col=sql.Identifier(relation_column),
        )
        logged_query(cr, query)
    # Translations copy
    query = sql.SQL("""
        INSERT INTO ir_translation (
            lang,
            module,
            name,
            res_id,
            src,
            state,
            type,
            value
        )
        SELECT
            it.lang,
            it.module,
            REPLACE(
                it.name,
                %(src_m)s || ',' || %(src_c)s,
                %(dst_m)s || ',' || %(dst_c)s
            ),
            dt.id,
            it.src,
            it.state,
            it.type,
            it.value
        FROM ir_translation AS it
        INNER JOIN {dst_t} AS dt ON dt.{rel_col} = it.res_id
        WHERE
            it.name = %(src_m)s || ',' || %(src_c)s OR
            it.name LIKE %(src_m)s || ',' || %(src_c)s || ',%%' OR
            (%(src_m)s = 'ir.ui.view' AND it.type = 'view')
        ON CONFLICT DO NOTHING
    """)
    for dest_col, src_col in zip(destination_columns, source_columns):
        logged_query(
            cr,
            query.format(
                dst_t=sql.Identifier(destination_table),
                rel_col=sql.Identifier(relation_column),
            ),
            {
                "dst_c": dest_col,
                "dst_m": destination_model,
                "src_c": src_col,
                "src_m": source_model,
            },
        )


def remove_tables_fks(cr, tables):
    """Remove foreign keys declared in ``tables``.

    This is useful when a table is not going to be used anymore, but you still
    don't want to delete it.

    If you keep FKs in that table, it will still get modifications when other
    tables are modified too; but if you're keeping that table as a log, that
    is a problem. Also, if some of the FK has no index, it could slow down
    deletion in other tables, even when this one has no more use.

    .. HINT::
        This method removes FKs that are *declared* in ``tables``,
        **not** FKs that *point* to those tables.

    :param [str, ...] tables:
        List of tables where the FKs were declared, and where they will be
        removed too. If a table doesn't exist, it is skipped.
    """
    drop_sql = sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}")
    for table in tables:
        cr.execute(
            """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE constraint_type = 'FOREIGN KEY' AND table_name = %s
            """,
            (table,),
        )
        for constraint in (row[0] for row in cr.fetchall()):
            logged_query(
                cr,
                drop_sql.format(
                    sql.Identifier(table),
                    sql.Identifier(constraint),
                ),
            )


def rename_columns(cr, column_spec):
    """
    Rename table columns. Typically called in the pre script.

    :param column_spec: a hash with table keys, with lists of tuples as \
    values. Tuples consist of (old_name, new_name). Use None for new_name \
    to trigger a conversion of old_name using get_legacy_name()
    """
    for table in column_spec.keys():
        for (old, new) in column_spec[table]:
            if new is None:
                new = get_legacy_name(old)
            logger.info("table %s, column %s: renaming to %s",
                        table, old, new)
            cr.execute(
                'ALTER TABLE "%s" RENAME "%s" TO "%s"' % (table, old, new,))
            old_index_name = "%s_%s_index" % (table, old)
            new_index_name = "%s_%s_index" % (table, new)
            if len(new_index_name) <= 63:
                cr.execute(
                    'ALTER INDEX IF EXISTS "%s" RENAME TO "%s"' %
                    (old_index_name, new_index_name)
                )


def rename_fields(env, field_spec, no_deep=False):
    """Rename fields. Typically called in the pre script. WARNING: If using
    this on base module, pass the argument ``no_deep`` with True value for
    avoiding the using of the environment (which is not yet loaded).

    This, in contrast of ``rename_columns``, performs all the steps for
    completely rename a field from one name to another. This is needed for
    making a complete renaming of a field with all their side features:
    translations, filters, exports...

    Call this method whenever you are not performing a pure SQL column renaming
    for other purposes (preserve a value for example).

    This method performs also the SQL column renaming, so only one call is
    needed.

    :param env: Environment/pool variable. The database cursor is the only
      thing needed, but added in prevision of TODO tasks for not breaking
      API later.
    :param field_spec: a list of tuples with the following elements:
      * Model name. The name of the Odoo model
      * Table name. The name of the SQL table for the model.
      * Old field name. The name of the old field.
      * New field name. The name of the new field.
    :param no_deep: If True, avoids to perform any operation that involves
      the environment. Not used for now.
    """
    cr = env.cr
    for model, table, old_field, new_field in field_spec:
        if column_exists(cr, table, old_field):
            rename_columns(cr, {table: [(old_field, new_field)]})
        # Rename corresponding field entry
        cr.execute("""
            UPDATE ir_model_fields
            SET name = %s
            WHERE name = %s
                AND model = %s
            """, (new_field, old_field, model),
        )
        # Rename translations
        cr.execute("""
            UPDATE ir_translation
            SET name = %s
            WHERE name = %s
                AND type = 'model'
            """, (
                "%s,%s" % (model, new_field),
                "%s,%s" % (model, old_field),
            ),
        )
        # Rename possible attachments (if field is Binary with attachment=True)
        if column_exists(cr, "ir_attachment", "res_field"):
            cr.execute("""
                UPDATE ir_attachment
                SET res_field = %s
                WHERE res_model = %s
                    AND res_field = %s
                """, (new_field, model, old_field)
            )
        # Rename appearances on export profiles
        # TODO: Rename when the field is part of a submodel (ex. m2one.field)
        cr.execute("""
            UPDATE ir_exports_line iel
            SET name = %s
            FROM ir_exports ie
            WHERE iel.name = %s
                AND ie.id = iel.export_id
                AND ie.resource = %s
            """, (new_field, old_field, model),
        )
        # Rename appearances on filters
        # Example of replaced domain: [['field', '=', self], ...]
        # TODO: Rename when the field is part of a submodel (ex. m2one.field)
        cr.execute("""
            UPDATE ir_filters
            SET domain = replace(domain, %(old_pattern)s, %(new_pattern)s)
            WHERE model_id = %%s
                AND domain ~ %(old_pattern)s
            """ % {
                'old_pattern': "$$'%s'$$" % old_field,
                'new_pattern': "$$'%s'$$" % new_field,
            }, (model, ),
        )
        # Examples of replaced contexts:
        # {'group_by': ['field', 'other_field'], 'other_key':value}
        # {'group_by': ['date_field:month']}
        # {'other_key': value, 'group_by': ['other_field', 'field']}
        # {'group_by': ['other_field'],'col_group_by': ['field']}
        cr.execute(r"""
            UPDATE ir_filters
            SET context = regexp_replace(
                context, %(old_pattern)s, %(new_pattern)s
            )
            WHERE model_id = %%s
                AND context ~ %(old_pattern)s
            """ % {
                'old_pattern': (
                    r"$$('group_by'|'col_group_by'):([^\]]*)"
                    r"'%s(:day|:week|:month|:year){0,1}'(.*?\])$$"
                ) % old_field,
                'new_pattern': r"$$\1:\2'%s\3'\4$$" % new_field,
            }, (model, ),
        )
        if table_exists(env.cr, 'mail_alias'):
            # Rename appearances on mail alias
            cr.execute("""
                UPDATE mail_alias ma
                SET alias_defaults =
                    replace(alias_defaults, %(old_pattern)s, %(new_pattern)s)
                FROM ir_model im
                WHERE ma.alias_model_id = im.id
                    AND im.model = %%s
                    AND ma.alias_defaults ~ %(old_pattern)s
                """ % {
                    'old_pattern': "$$'%s'$$" % old_field,
                    'new_pattern': "$$'%s'$$" % new_field,
                }, (model, ),
            )


def rename_tables(cr, table_spec):
    """
    Rename tables. Typically called in the pre script.
    This function also renames the id sequence if it exists and if it is
    not modified in the same run.

    :param table_spec: a list of tuples (old table name, new table name). Use \
    None for new_name to trigger a conversion of old_name to the result of \
    get_legacy_name()
    """
    # Append id sequences
    to_rename = [x[0] for x in table_spec]
    for old, new in list(table_spec):
        if new is None:
            new = get_legacy_name(old)
        if (table_exists(cr, old + '_id_seq') and
                old + '_id_seq' not in to_rename):
            table_spec.append((old + '_id_seq', new + '_id_seq'))
    for (old, new) in table_spec:
        if new is None:
            new = get_legacy_name(old)
        logger.info("table %s: renaming to %s",
                    old, new)
        cr.execute('ALTER TABLE "%s" RENAME TO "%s"' % (old, new,))
        # Rename indexes
        old_table_prefix_pattern = r"%s\_%%" % old.replace("_", r"\_")
        cr.execute(
            """
            SELECT index_rel.relname
            FROM pg_index AS i
            JOIN pg_class AS table_rel ON table_rel.oid = i.indrelid
            JOIN pg_class AS index_rel ON index_rel.oid = i.indexrelid
            WHERE table_rel.relname = %s AND index_rel.relname LIKE %s
            """,
            (new, old_table_prefix_pattern),
        )
        for old_index, in cr.fetchall():
            new_index = old_index.replace(old, new, 1)
            cr.execute(
                sql.SQL("ALTER INDEX {} RENAME TO {}").format(
                    sql.Identifier(old_index), sql.Identifier(new_index),
                )
            )
        # Rename constraints
        cr.execute(
            """
            SELECT pg_constraint.conname
            FROM pg_constraint
            INNER JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
            WHERE pg_class.relname = %s AND pg_constraint.conname LIKE %s
            """,
            (new, old_table_prefix_pattern),
        )
        for old_constraint, in cr.fetchall():
            new_constraint = old_constraint.replace(old, new, 1)
            cr.execute(
                sql.SQL("ALTER TABLE {} RENAME CONSTRAINT {} TO {}").format(
                    sql.Identifier(new),
                    sql.Identifier(old_constraint),
                    sql.Identifier(new_constraint),
                )
            )


def rename_models(cr, model_spec):
    """
    Rename models. Typically called in the pre script.
    :param model_spec: a list of tuples (old model name, new model name).

    Use case: if a model changes name, but still implements equivalent
    functionality you will want to update references in for instance
    relation fields.

    WARNING: This method doesn't rename the associated tables. For that,
    you need to call `rename_tables` method.
    """
    for (old, new) in model_spec:
        logger.info("model %s: renaming to %s",
                    old, new)
        _old = old.replace('.', '_')
        _new = new.replace('.', '_')
        logged_query(
            cr,
            'UPDATE ir_model SET model = %s '
            'WHERE model = %s', (new, old,),
        )
        logged_query(
            cr,
            'UPDATE ir_model_data SET model = %s '
            'WHERE model = %s', (new, old,),
        )
        logged_query(
            cr,
            "UPDATE ir_model_data SET name=%s "
            "WHERE name=%s AND model = 'ir.model'",
            ('model_' + _new, 'model_' + _old,),
        )
        underscore = "_" if version_info[0] < 12 else "__"
        logged_query(
            cr, """UPDATE ir_model_data imd
            SET name = 'field_' || '%s' || '%s' || imf.name
            FROM ir_model_fields imf
            WHERE imd.model = 'ir.model.fields'
                AND imd.name = 'field_' || '%s' || '%s' || imf.name
                AND imf.model = %s""",
            (AsIs(_new), AsIs(underscore), AsIs(_old), AsIs(underscore), old),
        )
        logged_query(
            cr,
            'UPDATE ir_attachment SET res_model = %s '
            'WHERE res_model = %s', (new, old,),
        )
        logged_query(
            cr,
            'UPDATE ir_model_fields SET model = %s '
            'WHERE model = %s', (new, old,),
        )
        logged_query(
            cr,
            "UPDATE ir_translation SET "
            "name=%s || substr(name, strpos(name, ',')) "
            "WHERE name LIKE %s",
            (new, old + ',%'),
        )
        logged_query(
            cr,
            "UPDATE ir_filters SET model_id = %s "
            "WHERE model_id = %s", (new, old,),
        )
        # Handle properties that reference to this model
        logged_query(
            cr,
            "SELECT id FROM ir_model_fields "
            "WHERE relation = %s AND ttype = 'many2one'", (old, ),
        )
        field_ids = [x[0] for x in cr.fetchall()]
        logged_query(
            cr,
            'UPDATE ir_model_fields SET relation = %s '
            'WHERE relation = %s', (new, old,),
        )
        if field_ids:
            logged_query(
                cr, """
                UPDATE ir_property
                SET value_reference = regexp_replace(
                    value_reference, %(old_pattern)s, %(new_pattern)s
                )
                WHERE fields_id IN %(field_ids)s
                AND value_reference ~ %(old_pattern)s""", {
                    'field_ids': tuple(field_ids),
                    'old_pattern': r"^%s,[ ]*([0-9]*)" % old,
                    'new_pattern': r"%s,\1" % new,
                },
            )
        # Update export profiles references
        logged_query(
            cr, "UPDATE ir_exports SET resource = %s WHERE resource = %s",
            (new, old),
        )
        if column_exists(cr, 'ir_act_server', 'model_name'):
            # model_name is a related field that in v11 becomes stored
            logged_query(
                cr,
                'UPDATE ir_act_server SET model_name = %s '
                'WHERE model_name = %s', (new, old,),
            )
        if is_module_installed(cr, 'email_template'):
            if table_exists(cr, 'email_template') and column_exists(
                    cr, 'email_template', 'model'):
                logged_query(
                    cr,
                    'UPDATE email_template SET model=%s'
                    'where model=%s', (new, old),
                )
        if is_module_installed(cr, 'mail'):
            # fortunately, the data model didn't change up to now
            logged_query(
                cr,
                'UPDATE mail_message SET model=%s where model=%s', (new, old),
            )
            if table_exists(cr, 'mail_message_subtype'):
                logged_query(
                    cr,
                    'UPDATE mail_message_subtype SET res_model=%s '
                    'where res_model=%s', (new, old),
                )
            if table_exists(cr, 'mail_template'):
                logged_query(
                    cr,
                    'UPDATE mail_template SET model=%s'
                    'where model=%s', (new, old),
                )
            if table_exists(cr, 'mail_followers'):
                logged_query(
                    cr,
                    'UPDATE mail_followers SET res_model=%s '
                    'where res_model=%s', (new, old),
                )
            if table_exists(cr, 'mail_activity'):
                logged_query(
                    cr,
                    'UPDATE mail_activity SET res_model=%s '
                    'where res_model=%s', (new, old),
                )

    # TODO: signal where the model occurs in references to ir_model


def rename_xmlids(cr, xmlids_spec, allow_merge=False):
    """
    Rename XML IDs. Typically called in the pre script.
    One usage example is when an ID changes module. In OpenERP 6 for example,
    a number of res_groups IDs moved to module base from other modules (
    although they were still being defined in their respective module).

    :param xmlids_spec: a list of tuples (old module.xmlid, new module.xmlid).
    :param allow_merge: if the new ID already exists, try to merge the records.
        This is recommended when renaming module categories, which are
        generated on the fly by the Odoo database initialization routine and
        may resurface over a longer period of time. In general though, this
        option should be avoided. Renaming to existing IDs is usually an
        error, and because this method is usually called in the pre-stage,
        the applied merge method is by SQL which is incomplete and can lead
        to inconsistencies in the database.
    """
    get_data_query = (
        """SELECT res_id, model FROM ir_model_data
        WHERE module=%s AND name=%s""")
    for (old, new) in xmlids_spec:
        if '.' not in old or '.' not in new:
            logger.error(
                'Cannot rename XMLID %s to %s: need the module '
                'reference to be specified in the IDs' % (old, new))
            continue
        cr.execute(get_data_query, tuple(old.split('.')))
        old_row = cr.fetchone()
        if not old_row:
            logger.info('XMLID %s not found when renaming to %s', old, new)
            continue
        if allow_merge:
            cr.execute(get_data_query, tuple(new.split('.')))
            new_row = cr.fetchone()
            if new_row:
                logger.info(
                    'XMLID %s already exists when renaming from %s: Merging.',
                    new, old)
                if new_row[1] != old_row[1]:
                    do_raise(
                        "Cannot merge XMLIDs %s, %s because they don't belong "
                        "to the same model (%s, %s)" % (
                            old, new, old_row[1], new_row[1]))
                table = old_row[1].replace('.', '_')
                if not table_exists(cr, table):
                    do_raise(
                        "Cannot merge XMLIDs %s, %s because the table I "
                        "guessed (%s) based on the model name (%s) does not "
                        "exist." % (old, new, table, old_row[1]))
                # Cannot import merge_records until after Odoo initialization
                from .openupgrade_merge_records import merge_records
                env = api.Environment(cr, SUPERUSER_ID, {})
                merge_records(
                    env, old_row[1], [old_row[0]], new_row[0],
                    method="sql", model_table=table)
                continue
        query = ("UPDATE ir_model_data SET module = %s, name = %s "
                 "WHERE module = %s and name = %s")
        logged_query(cr, query, tuple(new.split('.') + old.split('.')))


def add_xmlid(cr, module, xmlid, model, res_id, noupdate=False):
    """
    Adds an entry in ir_model_data. Typically called in the pre script.
    One usage example is when an entry has been add in the XML and there is
    a high probability that the user has already created the entry manually.
    For example, a currency was added in the XML data of the base module
    in OpenERP 6 but the user had already created this missing currency
    by hand in it's 5.0 database. In order to avoid having 2 identical
    currencies (which is in fact blocked by an sql_constraint), you have to
    add the entry in ir_model_data before the upgrade.
    """
    # Check if the XMLID doesn't already exists
    cr.execute(
        "SELECT id FROM ir_model_data WHERE module=%s AND name=%s "
        "AND model=%s",
        (module, xmlid, model))
    already_exists = cr.fetchone()
    if already_exists:
        return False
    else:
        query = "INSERT INTO ir_model_data ({fields}) VALUES ({values})"
        fields = [
            "create_uid",
            "create_date",
            "write_uid",
            "write_date",
            "noupdate",
            "name",
            "module",
            "model",
            "res_id",
        ]
        args = (
            SUPERUSER_ID,
            AsIs("(now() at time zone 'UTC')"),
            SUPERUSER_ID,
            AsIs("(now() at time zone 'UTC')"),
            noupdate,
            xmlid,
            module,
            model,
            res_id,
        )
        if version_info[0] < 14:
            fields += ["date_init", "date_update"]
            args += (
                AsIs("(now() at time zone 'UTC')"),
                AsIs("(now() at time zone 'UTC')"),
            )
        logged_query(
            cr,
            query.format(
                fields=",".join([_ for _ in fields]),
                values=",".join(["%s" for _ in args]),
            ),
            args,
        )
        return True


def drop_columns(cr, column_spec):
    """
    Drop columns but perform an additional check if a column exists.
    This covers the case of function fields that may or may not be stored.
    Consider that this may not be obvious: an additional module can govern
    a function fields' store properties.

    :param column_spec: a list of (table, column) tuples
    """
    for (table, column) in column_spec:
        logger.info("table %s: drop column %s",
                    table, column)
        if column_exists(cr, table, column):
            cr.execute('ALTER TABLE "%s" DROP COLUMN "%s"' %
                       (table, column))
        else:
            logger.warn("table %s: column %s did not exist",
                        table, column)


def update_workflow_workitems(cr, pool, ref_spec_actions):
    """Find all the workflow items from the target state to set them to
    the wanted state.

    When a workflow action is removed, from model, the objects whose states
    are in these actions need to be set to another to be able to continue the
    workflow properly.

    Run in pre-migration

    :param ref_spec_actions: list of tuples with couple of workflow.action's
        external ids. The first id is replaced with the second.
    :return: None

    .. versionadded:: 7.0
    """
    workflow_workitems = pool['workflow.workitem']
    ir_model_data_model = pool['ir.model.data']

    for (target_external_id, fallback_external_id) in ref_spec_actions:
        target_activity = ir_model_data_model.get_object(
            cr, SUPERUSER_ID,
            target_external_id.split(".")[0],
            target_external_id.split(".")[1],
        )
        fallback_activity = ir_model_data_model.get_object(
            cr, SUPERUSER_ID,
            fallback_external_id.split(".")[0],
            fallback_external_id.split(".")[1],
        )
        ids = workflow_workitems.search(
            cr, SUPERUSER_ID, [('act_id', '=', target_activity.id)]
        )
        if ids:
            logger.info(
                "Moving %d items in the removed workflow action (%s) to a "
                "fallback action (%s): %s",
                len(ids), target_activity.name, fallback_activity.name, ids
            )
            workflow_workitems.write(
                cr, SUPERUSER_ID, ids, {'act_id': fallback_activity.id}
            )


def delete_model_workflow(cr, model, drop_indexes=False):
    """
    Forcefully remove active workflows for obsolete models,
    to prevent foreign key issues when the orm deletes the model.

    :param cr:
        DB cursor.

    :param str model:
        Model name.

    :param bool drop_indexes:
        Do I drop indexes after finishing? If ``False``, those will be dropped
        by a subsequent update of the ``workflow`` module in normal Odoo
        probably.
    """
    # Save hours by adding needed indexes for affected FK constraints
    to_index = {
        "wkf_activity": ["subflow_id"],
        "wkf_instance": ["wkf_id"],
        "wkf_triggers": ["instance_id", "workitem_id"],
        "wkf_workitem": ["act_id"],
    }

    def _index_loop():
        for table_name, fields in to_index.items():
            for col_name in fields:
                index = sql.Identifier(
                    "{}_{}_index".format(table_name, col_name),
                )
                table = sql.Identifier(table_name)
                col = sql.Identifier(col_name)
                yield index, table, col

    for index, table, col in _index_loop():
        logged_query(
            cr,
            sql.SQL("""
                CREATE INDEX IF NOT EXISTS {} ON {}
                USING BTREE({})
            """).format(index, table, col)
        )
    # Delete workflows
    logged_query(
        cr,
        "DELETE FROM wkf_workitem WHERE act_id in "
        "( SELECT wkf_activity.id "
        "  FROM wkf_activity, wkf "
        "  WHERE wkf_id = wkf.id AND "
        "  wkf.osv = %s"
        ")", (model,))
    logged_query(
        cr,
        "DELETE FROM wkf WHERE osv = %s", (model,))
    # Remove temporary indexes if asked to do so
    if drop_indexes:
        for index, table, col in _index_loop():
            logged_query(cr, sql.SQL("DROP INDEX {}").format(index))


def warn_possible_dataloss(cr, pool, old_module, fields):
    """
    Use that function in the following case:
    if a field of a model was moved from a 'A' module to a 'B' module.
    ('B' depend on 'A'),
    This function will test if 'B' is installed.
    If not, count the number of different value and possibly warn the user.
    Use orm, so call from the post script.

    :param old_module: name of the old module
    :param fields: list of dictionary with the following keys:
        'table' : name of the table where the field is.
        'field' : name of the field that are moving.
        'new_module' : name of the new module

    .. versionadded:: 7.0
    """
    module_obj = pool.get('ir.module.module')
    for field in fields:
        module_ids = module_obj.search(
            cr, SUPERUSER_ID, [
                ('name', '=', field['new_module']),
                ('state', 'in', ['installed', 'to upgrade', 'to install'])
            ])
        if not module_ids:
            cr.execute(
                "SELECT count(*) FROM (SELECT %s from %s group by %s) "
                "as tmp" % (
                    field['field'], field['table'], field['field']))
            row = cr.fetchone()
            if row[0] == 1:
                # not a problem, that field wasn't used.
                # Just a loss of functionality
                logger.info(
                    "Field '%s' from module '%s' was moved to module "
                    "'%s' which is not installed: "
                    "No dataloss detected, only loss of functionality"
                    % (field['field'], old_module, field['new_module']))
            else:
                # there is data loss after the migration.
                message(
                    cr, old_module, None, None,
                    "Field '%s' was moved to module "
                    "'%s' which is not installed: "
                    "There were %s distinct values in this field.",
                    field['field'], field['new_module'], row[0])


def set_defaults(cr, pool, default_spec, force=False, use_orm=False):
    """
    Set default value. Useful for fields that are newly required. Uses orm, so
    call from the post script.

    :param pool: you can pass 'env' as well.
    :param default_spec: a hash with model names as keys. Values are lists \
    of tuples (field, value). None as a value has a special meaning: it \
    assigns the default value. If this value is provided by a function, the \
    function is called as the user that created the resource.
    :param force: overwrite existing values. To be used for assigning a non- \
    default value (presumably in the case of a new column). The ORM assigns \
    the default value as declared in the model in an earlier stage of the \
    process. Beware of issues with resources loaded from new data that \
    actually do require the model's default, in combination with the post \
    script possible being run multiple times.
    :param use_orm: If set to True, the write operation of the default value \
    will be triggered using ORM instead on an SQL clause (default).
    """

    def write_value(ids, field, value):
        logger.debug(
            "model %s, field %s: setting default value of resources %s to %s",
            model, field, ids, unicode(value))
        if use_orm:
            if version_info[0] <= 7:
                for res_id in ids:
                    # Iterating over ids here as a workaround for lp:1131653
                    obj.write(cr, SUPERUSER_ID, [res_id], {field: value})
            else:
                if api and isinstance(pool, api.Environment):
                    obj.browse(ids).write({field: value})
                else:
                    obj.write(cr, SUPERUSER_ID, ids, {field: value})
        else:
            query, params = "UPDATE %s SET %s = %%s WHERE id IN %%s" % (
                obj._table, field), (value, tuple(ids))
            # handle fields inherited from somewhere else
            if version_info[0] >= 10:
                columns = obj._fields
            else:
                columns = obj._columns
            if field not in columns:
                query, params = None, None
                for model_name in obj._inherits:
                    if obj._inherit_fields[field][0] != model_name:
                        continue
                    col = obj._inherits[model_name]
                    # this is blatantly stolen and adapted from
                    # https://github.com/OCA/OCB/blob/def7db0b93e45eda7b51b3b61
                    # bae1e975d07968b/openerp/osv/orm.py#L4307
                    nids = []
                    for sub_ids in cr.split_for_in_conditions(ids):
                        cr.execute(
                            'SELECT DISTINCT %s FROM %s WHERE id IN %%s' % (
                                col, obj._table), (sub_ids,))
                        nids.extend(x for x, in cr.fetchall())
                    query, params = "UPDATE %s SET %s = %%s WHERE id IN %%s" %\
                        (pool[model_name]._table, field), (value, tuple(nids))
            if not query:
                do_raise("Can't set default for %s on %s!" % (
                    field, obj._name))
            # cope with really big tables
            for sub_ids in cr.split_for_in_conditions(params[1]):
                cr.execute(query, (params[0], sub_ids))

    for model in default_spec.keys():
        try:
            obj = pool[model]
        except KeyError:
            do_raise(
                "Migration: error setting default, no such model: %s" % model)

        for field, value in default_spec[model]:
            domain = not force and [(field, '=', False)] or []
            if api and isinstance(pool, api.Environment):
                ids = obj.search(domain).ids
            else:
                ids = obj.search(cr, SUPERUSER_ID, domain)
            if not ids:
                continue
            if value is None:
                if version_info[0] > 7:
                    if api and isinstance(pool, api.Environment):
                        value = obj.default_get([field]).get(field)
                    else:
                        value = obj.default_get(
                            cr, SUPERUSER_ID, [field]).get(field)
                    if value:
                        write_value(ids, field, value)
                else:
                    # For older versions, compute defaults per user anymore
                    # if the default is a method. If we need this in newer
                    # versions, make it a parameter.
                    if field in obj._defaults:
                        if not callable(obj._defaults[field]):
                            write_value(ids, field, obj._defaults[field])
                        else:
                            cr.execute(
                                "SELECT id, COALESCE(create_uid, 1) FROM %s " %
                                obj._table + "WHERE id in %s", (tuple(ids),))
                            # Execute the function once per user_id
                            user_id_map = {}
                            for row in cr.fetchall():
                                user_id_map.setdefault(row[1], []).append(
                                    row[0])
                            for user_id in user_id_map:
                                write_value(
                                    user_id_map[user_id], field,
                                    obj._defaults[field](
                                        obj, cr, user_id, None))
                    else:
                        error = (
                            "OpenUpgrade: error setting default, field %s "
                            "with None default value not in %s' _defaults" % (
                                field, model))
                        logger.error(error)
                        # this exc. seems to get lost in a higher up try block
                        except_orm("OpenUpgrade", error)
            else:
                write_value(ids, field, value)


def logged_query(cr, query, args=None, skip_no_result=False):
    """
    Logs query and affected rows at level DEBUG.

    :param query: a query string suitable to pass to cursor.execute()
    :param args: a list, tuple or dictionary passed as substitution values
      to cursor.execute().
    :param skip_no_result: If True, then logging details are only shown
      if there are affected records.
    """
    if args is None:
        args = ()
    args = tuple(args) if type(args) == list else args
    log_level = _logging_module.DEBUG
    log_msg = False
    start = datetime.now()
    try:
        cr.execute(query, args)
    except (ProgrammingError, IntegrityError):
        log_level = _logging_module.ERROR
        log_msg = "Error after %(duration)s running %(full_query)s"
        raise
    else:
        if not skip_no_result or cr.rowcount:
            log_msg = ('%(rowcount)d rows affected after '
                       '%(duration)s running %(full_query)s')
    finally:
        duration = datetime.now() - start
        if log_msg:
            try:
                full_query = tools.ustr(cr._obj.query)
            except AttributeError:
                full_query = tools.ustr(cr.mogrify(query, args))
            logger.log(log_level, log_msg, {
                "full_query": full_query,
                "rowcount": cr.rowcount,
                "duration": duration,
            })
    return cr.rowcount


def update_module_names(cr, namespec, merge_modules=False):
    """Deal with changed module names, making all the needed changes on the
    related tables, like XML-IDs, translations, and so on.

    :param namespec: list of tuples of (old name, new name)
    :param merge_modules: Specify if the operation should be a merge instead
        of just a renaming.
    """
    for (old_name, new_name) in namespec:
        query = "SELECT id FROM ir_module_module WHERE name = %s"
        cr.execute(query, [new_name])
        row = cr.fetchone()
        if row and merge_modules:
            # Delete meta entries, that will avoid the entry removal
            # They will be recreated by the new module anyhow.
            query = "SELECT id FROM ir_module_module WHERE name = %s"
            cr.execute(query, [old_name])
            row = cr.fetchone()
            if row:
                old_id = row[0]
                query = "DELETE FROM ir_model_constraint WHERE module = %s"
                logged_query(cr, query, [old_id])
                query = "DELETE FROM ir_model_relation WHERE module = %s"
                logged_query(cr, query, [old_id])
        else:
            query = "UPDATE ir_module_module SET name = %s WHERE name = %s"
            logged_query(cr, query, (new_name, old_name))
            query = ("UPDATE ir_model_data SET name = %s "
                     "WHERE name = %s AND module = 'base' AND "
                     "model='ir.module.module' ")
            logged_query(cr, query,
                         ("module_%s" % new_name, "module_%s" % old_name))
        # The subselect allows to avoid duplicated XML-IDs
        query = ("UPDATE ir_model_data SET module = %s "
                 "WHERE module = %s AND name NOT IN "
                 "(SELECT name FROM ir_model_data WHERE module = %s)")
        logged_query(cr, query, (new_name, old_name, new_name))
        # Rename the remaining occurrences for let Odoo's update process
        # to auto-remove related resources
        query = ("UPDATE ir_model_data "
                 "SET name = name || '_openupgrade_' || id, "
                 "module = %s "
                 "WHERE module = %s")
        logged_query(cr, query, (new_name, old_name))
        query = ("UPDATE ir_module_module_dependency SET name = %s "
                 "WHERE name = %s")
        logged_query(cr, query, (new_name, old_name))
        if version_info[0] > 7:
            query = ("UPDATE ir_translation SET module = %s "
                     "WHERE module = %s")
            logged_query(cr, query, (new_name, old_name))
        if merge_modules:
            # Conserve old_name's state if new_name is uninstalled
            logged_query(
                cr,
                "UPDATE ir_module_module m1 "
                "SET state=m2.state, latest_version=m2.latest_version "
                "FROM ir_module_module m2 WHERE m1.name=%s AND "
                "m2.name=%s AND m1.state='uninstalled'",
                (new_name, old_name),
            )
            query = "DELETE FROM ir_module_module WHERE name = %s"
            logged_query(cr, query, [old_name])
            logged_query(
                cr,
                "DELETE FROM ir_model_data WHERE module = 'base' "
                "AND model='ir.module.module' AND name = %s",
                ('module_%s' % old_name,),
            )


def add_ir_model_fields(cr, columnspec):
    """
    Typically, new columns on ir_model_fields need to be added in a very
    early stage in the upgrade process of the base module, in raw sql
    as they need to be in place before any model gets initialized.
    Do not use for fields with additional SQL constraints, such as a
    reference to another table or the cascade constraint, but craft your
    own statement taking them into account.

    :param columnspec: tuple of (column name, column type)
    """
    for column in columnspec:
        query = 'ALTER TABLE ir_model_fields ADD COLUMN %s %s' % (
            column)
        logged_query(cr, query, [])


def get_legacy_name(original_name):
    """
    Returns a versioned name for legacy tables/columns/etc
    Use this function instead of some custom name to avoid
    collisions with future or past legacy tables/columns/etc

    :param original_name: the original name of the column
    :param version: current version as passed to migrate()
    """
    return 'openupgrade_legacy_' + '_'.join(
        map(str, version_info[0:2])) + '_' + original_name


def m2o_to_x2m(cr, model, table, field, source_field):
    """
    Transform many2one relations into one2many or many2many.
    Use rename_columns in your pre-migrate script to retain the column's old
    value, then call m2o_to_x2m in your post-migrate script.

    WARNING: If converting to one2many, there can be data loss, because only
    one inverse record can be mapped in a one2many, but you can have multiple
    many2one pointing to the same target. Use it when the use case allows this
    conversion.

    :param model: The target model registry object
    :param table: The source table
    :param field: The new field name on the target model
    :param source_field: the (renamed) many2one column on the source table.

    .. versionadded:: 8.0
    """
    columns = getattr(model, '_columns', False) or getattr(model, '_fields')
    if not columns.get(field):
        do_raise("m2o_to_x2m: field %s doesn't exist in model %s" % (
            field, model._name))
    m2m_types = []
    if many2many:
        m2m_types.append(many2many)
    if Many2many:
        m2m_types.append(Many2many)
    o2m_types = []
    if one2many:
        o2m_types.append(one2many)
    if One2many:
        o2m_types.append(One2many)
    if isinstance(columns[field], tuple(m2m_types)):
        column = columns[field]
        if hasattr(many2many, '_sql_names'):  # >= 6.1 and < 10.0
            rel, id1, id2 = many2many._sql_names(column, model)
        elif hasattr(column, 'relation'):  # >= 10.0
            rel, id1, id2 = column.relation, column.column1, column.column2
        else:  # <= 6.0
            rel, id1, id2 = column._rel, column._id1, column._id2
        logged_query(
            cr,
            """
            INSERT INTO %s (%s, %s)
            SELECT id, %s
            FROM %s
            WHERE %s is not null
            """ %
            (rel, id1, id2, source_field, table, source_field))
    elif isinstance(columns[field], tuple(o2m_types)):
        if isinstance(columns[field], One2many):  # >= 8.0
            target_table = model.env[columns[field].comodel_name]._table
            target_field = columns[field].inverse_name
        else:
            target_table = model.pool[columns[field]._obj]._table
            target_field = columns[field]._fields_id
        logged_query(
            cr,
            """
            UPDATE %(target_table)s AS target
            SET %(target_field)s=source.id
            FROM %(source_table)s AS source
            WHERE source.%(source_field)s=target.id
            """ % {'target_table': target_table,
                   'target_field': target_field,
                   'source_field': source_field,
                   'source_table': table})
    else:
        do_raise(
            "m2o_to_x2m: field %s of model %s is not a "
            "many2many/one2many one" % (field, model._name))


# Backwards compatibility
def m2o_to_m2m(cr, model, table, field, source_field):
    """
    Recreate relations in many2many fields that were formerly
    many2one fields. Use rename_columns in your pre-migrate
    script to retain the column's old value, then call m2o_to_m2m
    in your post-migrate script.

    :param model: The target model registry object
    :param table: The source table
    :param field: The field name of the target model
    :param source_field: the many2one column on the source table.

    .. versionadded:: 7.0
    .. deprecated:: 8.0
       Use :func:`m2o_to_x2m` instead.
    """
    return m2o_to_x2m(cr, model, table, field, source_field)


def float_to_integer(cr, table, field):
    """
    Change column type from float to integer. It will just
    truncate the float value (It won't round it)

    :param table: The table
    :param field: The field name for which we want to change the type

    .. versionadded:: 8.0
    """
    logged_query(
        cr,
        "ALTER TABLE %(table)s "
        "ALTER COLUMN %(field)s "
        "TYPE integer" % {
            'table': table,
            'field': field,
        })


def map_values(
        cr, source_column, target_column, mapping,
        model=None, table=None, write='sql'):
    """
    Map old values to new values within the same model or table. Old values
    presumably come from a legacy column.
    You will typically want to use it in post-migration scripts.

    :param cr: The database cursor
    :param source_column: the database column that contains old values to be \
    mapped
    :param target_column: the database column, or model field (if 'write' is \
    'orm') that the new values are written to
    :param mapping: list of tuples [(old value, new value)]
        Old value True represents "is set", False "is not set".
    :param model: used for writing if 'write' is 'orm', or to retrieve the \
    table if 'table' is not given.
    :param table: the database table used to query the old values, and write \
    the new values (if 'write' is 'sql')
    :param write: Either 'orm' or 'sql'. Note that old ids are always \
    identified by an sql read.

    This method does not support mapping m2m, o2m or property fields. \
    For o2m you can migrate the inverse field's column instead.

    .. versionadded:: 8.0
    """

    if write not in ('sql', 'orm'):
        logger.exception(
            "map_values is called with unknown value for write param: %s",
            write)
    if not table:
        if not model:
            logger.exception("map_values is called with no table and no model")
        table = model._table
    if source_column == target_column:
        logger.exception(
            "map_values is called with the same value for source and old"
            " columns : %s",
            source_column)
    for old, new in mapping:
        new = "'%s'" % new

        if old is True:
            old = 'NOT NULL'
            op = 'IS'
        elif old is False:
            old = 'NULL'
            op = 'IS'
        else:
            old = "'%s'" % old
            op = '='

        values = {
            'table': table,
            'source': source_column,
            'target': target_column,
            'old': old,
            'new': new,
            'op': op,
        }

        if write == 'sql':
            query = """UPDATE %(table)s
                       SET %(target)s = %(new)s
                       WHERE %(source)s %(op)s %(old)s""" % values
        else:
            query = """SELECT id FROM %(table)s
                       WHERE %(source)s %(op)s %(old)s""" % values
        logged_query(cr, query, values)
        if write == 'orm':
            model.write(
                cr, SUPERUSER_ID,
                [row[0] for row in cr.fetchall()],
                {target_column: new})


def message(cr, module, table, column,
            message, *args, **kwargs):
    """
    Log handler for non-critical notifications about the upgrade.
    To be extended with logging to a table for reporting purposes.

    :param module: the module name that the message concerns
    :param table: the model that this message concerns (may be False, \
    but preferably not if 'column' is defined)
    :param column: the column that this message concerns (may be False)

    .. versionadded:: 7.0
    """
    argslist = list(args or [])
    prefix = ': '
    if column:
        argslist.insert(0, column)
        prefix = ', column %s' + prefix
    if table:
        argslist.insert(0, table)
        prefix = ', table %s' + prefix
    argslist.insert(0, module)
    prefix = 'Module %s' + prefix

    logger.warn(prefix + message, *argslist, **kwargs)


def deactivate_workflow_transitions(cr, model, transitions=None):
    """
    Disable workflow transitions for workflows on a given model.
    This can be necessary for automatic workflow transitions when writing
    to an object via the ORM in the post migration step.
    Returns a dictionary to be used on reactivate_workflow_transitions

    :param model: the model for which workflow transitions should be \
    deactivated
    :param transitions: a list of ('module', 'name') xmlid tuples of \
    transitions to be deactivated. Don't pass this if there's no specific \
    reason to do so, the default is to deactivate all transitions

    .. versionadded:: 7.0
    """
    transition_ids = []
    if transitions:
        data_obj = registry.get(cr.dbname)['ir.model.data']
        for module, name in transitions:
            try:
                transition_ids.append(
                    data_obj.get_object_reference(
                        cr, SUPERUSER_ID, module, name)[1])
            except ValueError:
                continue
    else:
        cr.execute(
            '''select distinct t.id
            from wkf w
            join wkf_activity a on a.wkf_id=w.id
            join wkf_transition t
                on t.act_from=a.id or t.act_to=a.id
            where w.osv=%s''', (model,))
        transition_ids = [i for i, in cr.fetchall()]
    cr.execute(
        'select id, condition from wkf_transition where id in %s',
        (tuple(transition_ids),))
    transition_conditions = dict(cr.fetchall())
    cr.execute(
        "update wkf_transition set condition = 'False' WHERE id in %s",
        (tuple(transition_ids),))
    return transition_conditions


def reactivate_workflow_transitions(cr, transition_conditions):
    """
    Reactivate workflow transition previously deactivated by
    deactivate_workflow_transitions.

    :param transition_conditions: a dictionary returned by \
    deactivate_workflow_transitions

    .. versionadded:: 7.0
    .. deprecated:: 11.0
       Workflows were removed from Odoo as of version 11.0
    """
    for transition_id, condition in transition_conditions.iteritems():
        cr.execute(
            'update wkf_transition set condition = %s where id = %s',
            (condition, transition_id))


# Global var to count call quantity to an openupgrade function
openupgrade_call_logging = {}


def logging(args_details=False, step=False):
    """
    This is a decorator for any sub functions called in an OpenUpgrade script.
    (pre or post migration script)

    Decorate functions that can take time, or for debug / development purpose.

    if a function is decorated, a log will be written each time the function
    is called.

    :param args_details: if True, arguments details are given in the log
    :param step: The log will be done only every step times.

    Typical use::

        @openupgrade.logging()
        def migrate_stock_warehouses(cr)
            # some custom code

        @openupgrade.logging(step=1000)
        def migrate_partner(cr, partner):
            # some custom code

        @openupgrade.migrate()
        def migrate(cr, version):
            # some custom code
            migrate_stock_warehouses(cr)

            for partner in partners:
                migrate_partner(cr, partner)

    """
    def wrap(func):

        @wraps(func)
        def wrapped_function(*args, **kwargs):
            to_log = True
            msg = "Executing method %s" % func.__name__
            # Count calls
            if step:
                # Compute unique name
                unique_name = '%s.%s' % (func.__module__, func.__name__)
                if unique_name not in openupgrade_call_logging:
                    openupgrade_call_logging[unique_name] = 0
                openupgrade_call_logging[unique_name] += 1
                current = openupgrade_call_logging[unique_name]
                if current == 1 or current % step == 0:
                    msg += " ; Calls quantity : %d" % current
                    if current == 1:
                        msg += " ; Logging Step : %d" % step
                else:
                    to_log = False
            # Log Args
            if args_details and to_log:
                if args:
                    msg += " ; args : %s" % str(args)
                if kwargs:
                    msg += " ; kwargs : %s" % str(kwargs)
            if to_log:
                logger.info(msg)
            return func(*args, **kwargs)

        return wrapped_function
    return wrap


def migrate(no_version=False, use_env=None, uid=None, context=None):
    """
    This is the decorator for the migrate() function
    in migration scripts.

    Set argument `no_version` to True if the method has to be taken into
    account if the module is installed during a migration.

    Set argument `use_env` if you want an v8+ environment instead of a plain
    cursor. Starting from version 10, this is the default

    The arguments `uid` and `context` can be set when an evironment is
    requested. In the cursor case, they're ignored.

    The migration function's signature must be `func(cr, version)` if
    `use_env` is `False` or not set and the version is below 10, or
    `func(env, version)` if `use_env` is `True` or not set and the version is
    10 or higher.

    Return when the `version` argument is not defined and `no_version` is
    False and log execeptions.

    Retrieve debug context data from the frame above for
    logging purposes.
    """
    def wrap(func):

        @wraps(func)
        def wrapped_function(cr, version):
            stage = 'unknown'
            module = 'unknown'
            filename = 'unknown'
            with ExitStack() as contextmanagers:
                contextmanagers.enter_context(savepoint(cr))
                use_env2 = use_env is None and version_info[0] >= 10 or use_env
                if use_env2:
                    assert version_info[0] >= 8, 'you need at least v8'
                    contextmanagers.enter_context(api.Environment.manage())
                try:
                    frame = inspect.getargvalues(inspect.stack()[1][0])
                    stage = frame.locals['stage']
                    module = frame.locals['pkg'].name
                    # Python3: fetch pyfile from locals, not fp
                    filename = frame.locals.get(
                        'pyfile') or frame.locals['fp'].name
                except Exception as exc:
                    logger.error(
                        "'migrate' decorator: failed to inspect "
                        "the frame above: %s",
                        exc
                    )
                if not version and not no_version:
                    return
                logger.info(
                    "%s: %s-migration script called with version %s",
                    module,
                    stage,
                    version
                )
                try:
                    # The actual function is called here
                    func(
                        api.Environment(
                            cr, uid or SUPERUSER_ID, context or {})
                        if use_env2 else cr, version)
                except Exception as exc:
                    error_message = \
                        repr(exc) if sys.version_info[0] == 2 else str(exc)
                    logger.error(
                        "%s: error in migration script %s: %s",
                        module, filename, error_message)
                    logger.exception(exc)
                    raise

        return wrapped_function
    return wrap


def move_field_m2o(
        cr, pool,
        registry_old_model, field_old_model, m2o_field_old_model,
        registry_new_model, field_new_model,
        quick_request=True, compute_func=None, binary_field=False):
    """
    Use that function in the following case:
    A field moves from a model A to the model B with : A -> m2o -> B.
    (For exemple product_product -> product_template)
    This function manage the migration of this field.
    available on post script migration.
    :param registry_old_model: registry of the model A;
    :param field_old_model: name of the field to move in model A;
    :param m2o_field_old_model: name of the field of the table of the model A \
    that link model A to model B;
    :param registry_new_model: registry of the model B;
    :param field_new_model: name of the field to move in model B;
    :param quick_request: Set to False, if you want to use write function to \
    update value; Otherwise, the function will use UPDATE SQL request;
    :param compute_func: This a function that receives 4 parameters: \
    cr, pool: common args;\
    id: id of the instance of Model B\
    vals:  list of different values.\
    This function must return a unique value that will be set to the\
    instance of Model B which id is 'id' param;\
    If compute_func is not set, the algorithm will take the value that\
    is the most present in vals.\
    :binary_field: Set to True if the migrated field is a binary field

    .. versionadded:: 8.0
    """
    def default_func(cr, pool, id, vals):
        """This function return the value the most present in vals."""
        quantity = {}.fromkeys(set(vals), 0)
        for val in vals:
            quantity[val] += 1
        res = vals[0]
        for val in vals:
            if quantity[res] < quantity[val]:
                res = val
        return res

    logger.info("Moving data from '%s'.'%s' to '%s'.'%s'" % (
        registry_old_model, field_old_model,
        registry_new_model, field_new_model))

    table_old_model = pool[registry_old_model]._table
    table_new_model = pool[registry_new_model]._table
    # Manage regular case (all the value are identical)
    cr.execute(
        " SELECT %s"
        " FROM %s"
        " GROUP BY %s"
        " HAVING count(*) = 1;" % (
            m2o_field_old_model, table_old_model, m2o_field_old_model
        ))
    ok_ids = [x[0] for x in cr.fetchall()]
    if quick_request:
        query = (
            " UPDATE %s as new_table"
            " SET %s=("
            "    SELECT old_table.%s"
            "    FROM %s as old_table"
            "    WHERE old_table.%s=new_table.id"
            "    LIMIT 1) "
            " WHERE id in %%s" % (
                table_new_model, field_new_model, field_old_model,
                table_old_model, m2o_field_old_model))
        logged_query(cr, query, [tuple(ok_ids)])
    else:
        query = (
            " SELECT %s, %s"
            " FROM %s "
            " WHERE %s in %%s"
            " GROUP BY %s, %s" % (
                m2o_field_old_model, field_old_model, table_old_model,
                m2o_field_old_model, m2o_field_old_model, field_old_model))
        cr.execute(query, [tuple(ok_ids)])
        for res in cr.fetchall():
            if res[1] and binary_field:
                pool[registry_new_model].write(
                    cr, SUPERUSER_ID, res[0],
                    {field_new_model: res[1][:]})
            else:
                pool[registry_new_model].write(
                    cr, SUPERUSER_ID, res[0],
                    {field_new_model: res[1]})

    # Manage non-determinist case (some values are different)
    func = compute_func if compute_func else default_func
    cr.execute(
        " SELECT %s "
        " FROM %s "
        " GROUP BY %s having count(*) != 1;" % (
            m2o_field_old_model, table_old_model, m2o_field_old_model
        ))
    ko_ids = [x[0] for x in cr.fetchall()]
    for ko_id in ko_ids:
        query = (
            " SELECT %s"
            " FROM %s"
            " WHERE %s = %s;" % (
                field_old_model, table_old_model, m2o_field_old_model, ko_id))
        cr.execute(query)
        if binary_field:
            vals = [str(x[0][:]) if x[0] else False for x in cr.fetchall()]
        else:
            vals = [x[0] for x in cr.fetchall()]
        value = func(cr, pool, ko_id, vals)
        if quick_request:
            query = (
                " UPDATE %s"
                " SET %s=%%s"
                " WHERE id = %%s" % (table_new_model, field_new_model))
            logged_query(
                cr, query, (value, ko_id))
        else:
            pool[registry_new_model].write(
                cr, SUPERUSER_ID, [ko_id],
                {field_new_model: value})


def convert_field_to_html(cr, table, field_name, html_field_name):
    """
    Convert field value to HTML value.

    .. versionadded:: 7.0
    """
    if version_info[0] < 7:
        logger.error("You cannot use this method in an OpenUpgrade version "
                     "prior to 7.0.")
        return
    cr.execute(
        "SELECT id, %(field)s FROM %(table)s WHERE %(field)s IS NOT NULL" % {
            'field': field_name,
            'table': table,
        }
    )
    for row in cr.fetchall():
        logged_query(
            cr, "UPDATE %(table)s SET %(field)s = %%s WHERE id = %%s" % {
                'field': html_field_name,
                'table': table,
            }, (plaintext2html(row[1]), row[0])
        )


def date_to_datetime_tz(
        cr, table_name, user_field_name, date_field_name, datetime_field_name):
    """ Take the related user's timezone into account when converting
    date field to datetime in a given table.
    This function must be call in post migration script.

    :param table_name : Name of the table where the field is;
    :param user_field_name : The name of the user field (res.users);
    :param date_field_name : The name of the old date field; \
    (Typically a legacy name, set in pre-migration script)
    :param datetime_field_name : The name of the new date field;

    .. versionadded:: 8.0
    """
    cr.execute(
        """
        SELECT distinct(rp.tz)
        FROM %s my_table, res_users ru, res_partner rp
        WHERE rp.tz IS NOT NULL
            AND my_table.%s=ru.id
            AND ru.partner_id=rp.id
        """ % (table_name, user_field_name,))
    for timezone, in cr.fetchall():
        cr.execute("SET TIMEZONE=%s", (timezone,))
        values = {
            'table_name': table_name,
            'date_field_name': date_field_name,
            'datetime_field_name': datetime_field_name,
            'timezone': timezone,
            'user_field_name': user_field_name,
        }
        logged_query(
            cr,
            """
            UPDATE %(table_name)s my_table
            SET %(datetime_field_name)s =
                my_table.%(date_field_name)s::TIMESTAMP AT TIME ZONE 'UTC'
            FROM res_partner rp, res_users ru
            WHERE my_table.%(date_field_name)s IS NOT NULL
                AND my_table.%(user_field_name)s=ru.id
                AND ru.partner_id=rp.id
                AND rp.tz='%(timezone)s';
            """ % values)
    cr.execute("RESET TIMEZONE")


def is_module_installed(cr, module):
    """ Check if `module` is installed.

    :return: True / False
    """
    cr.execute(
        "SELECT id FROM ir_module_module "
        "WHERE name=%s and state IN ('installed', 'to upgrade')", (module,))
    return bool(cr.fetchone())


def lift_constraints(cr, table, column):
    """Lift all constraints on column in table.
    Typically, you use this in a pre-migrate script where you adapt references
    for many2one fields with changed target objects.
    If everything went right, the constraints will be recreated"""
    cr.execute(
        'select relname, array_agg(conname) from '
        '(select t1.relname, c.conname '
        'from pg_constraint c '
        'join pg_attribute a '
        'on c.confrelid=a.attrelid and a.attnum=any(c.conkey) '
        'join pg_class t on t.oid=a.attrelid '
        'join pg_class t1 on t1.oid=c.conrelid '
        'where t.relname=%(table)s and attname=%(column)s '
        'union select t.relname, c.conname '
        'from pg_constraint c '
        'join pg_attribute a '
        'on c.conrelid=a.attrelid and a.attnum=any(c.conkey) '
        'join pg_class t on t.oid=a.attrelid '
        'where relname=%(table)s and attname=%(column)s) in_out '
        'group by relname',
        {
            'table': table,
            'column': column,
        })
    for table, constraints in cr.fetchall():
        cr.execute(
            'alter table %s drop constraint %s',
            (AsIs(table), AsIs(', drop constraint '.join(constraints)))
        )


@contextmanager
def savepoint(cr):
    """return a context manager wrapping postgres savepoints"""
    if hasattr(cr, 'savepoint'):
        with cr.savepoint():
            yield
    else:
        name = uuid.uuid1().hex
        cr.execute('SAVEPOINT "%s"' % name)
        try:
            yield
            cr.execute('RELEASE SAVEPOINT "%s"' % name)
        except Exception:
            cr.execute('ROLLBACK TO SAVEPOINT "%s"' % name)
            raise


def rename_property(cr, model, old_name, new_name):
    """Rename property old_name owned by model to new_name. This should happen
    in a pre-migration script."""
    cr.execute(
        "update ir_model_fields f set name=%s "
        "from ir_model m "
        "where m.id=f.model_id and m.model=%s and f.name=%s "
        "returning f.id",
        (new_name, model, old_name))
    field_ids = tuple(i for i, in cr.fetchall())
    cr.execute(
        "update ir_model_data set name=%s where model='ir.model.fields' and "
        "res_id in %s",
        ('%s,%s' % (model, new_name), field_ids))
    cr.execute(
        "update ir_property set name=%s where fields_id in %s",
        (new_name, field_ids))


def delete_record_translations(cr, module, xml_ids):
    """Cleanup translations of specific records in a module.

    :param module: module name
    :param xml_ids: a tuple or list of xml record IDs
    """
    if not isinstance(xml_ids, (list, tuple)):
        do_raise("XML IDs %s must be a tuple or list!" % (xml_ids))

    cr.execute("""
        SELECT model, res_id
        FROM ir_model_data
        WHERE module = %s AND name in %s
    """, (module, tuple(xml_ids),))
    for row in cr.fetchall():
        query = ("""
            DELETE FROM ir_translation
            WHERE module = %s AND name LIKE %s AND res_id = %s;
        """)
        logged_query(cr, query, (module, row[0] + ',%', row[1],))


def disable_invalid_filters(env):
    """It analyzes all the existing active filters to check if they are still
    correct. If not, they are disabled for avoiding errors when clicking on
    them, or worse, if they are default filters when opening the model/action.

    To be run at the base end-migration script for having a general scope. Only
    assured to work on > v8.

    :param env: Environment parameter.
    """
    if target_version and not is_target_version:
        logger.info(
            "Deferring `disable_invalid_filters` until this migration reaches "
            "target version %s", target_version)
        return
    try:
        from odoo.tools.safe_eval import safe_eval
    except ImportError:
        from openerp.tools.safe_eval import safe_eval
    import time
    try:
        basestring  # noqa: F823
    except NameError:  # For Python 3 compatibility
        basestring = str

    def format_message(f):
        msg = "FILTER DISABLED: "
        if f.user_id:
            msg += "Filter '%s' for user '%s'" % (f.name, f.user_id.name)
        else:
            msg += "Global Filter '%s'" % f.name
        msg += " for model '%s' has been disabled " % f.model_id
        return msg

    filters = env['ir.filters'].search([('domain', '!=', '[]')])
    for f in filters:
        if f.model_id not in env:
            continue  # Obsolete or invalid model
        model = env[f.model_id]
        columns = (
            getattr(model, '_columns', False) or getattr(model, '_fields')
        )
        # DOMAIN
        try:
            with savepoint(env.cr):
                # Strange artifact found in a filter
                domain = f.domain.replace('%%', '%')
                model.search(
                    safe_eval(domain, {'time': time, 'uid': env.uid}),
                    limit=1,
                )
        except Exception:
            logger.warning(
                format_message(f) + "as it contains an invalid domain."
            )
            f.active = False
            continue
        # CONTEXT GROUP BY
        try:
            context = safe_eval(f.context, {'time': time, 'uid': env.uid})
            assert(isinstance(context, dict))
        except Exception:
            logger.warning(
                format_message(f) + "as it contains an invalid context %s.",
                f.context
            )
            f.active = False
            continue
        keys = ['group_by', 'col_group_by']
        for key in keys:
            if not context.get(key):
                continue
            g = context[key]
            if not g:
                continue
            if isinstance(g, basestring):
                g = [g]
            for field_expr in g:
                field = field_expr.split(':')[0]  # Remove date specifiers
                if not columns.get(field):
                    logger.warning(
                        format_message(f) +
                        "as it contains an invalid %s." % key
                    )
                    f.active = False
                    break


def add_fields(env, field_spec):
    """This method adds all the needed stuff for having a new field populated
    in the DB (SQL column, ir.model.fields entry, ir.model.data entry...).

    It's intended for being run in pre-migration scripts for pre-populating
    fields that are going to be declared later in the module.

    NOTE: This is not needed in >=v12, as now Odoo
    always add the XML-ID entry:
    https://github.com/odoo/odoo/blob/9201f92a4f29a53a014b462469f27b32dca8fc5a/
    odoo/addons/base/models/ir_model.py#L794-L802, but you can still call
    this method for consistency and for avoiding to know the internal PG
    column type.

    :param: field_spec: List of tuples with the following expected elements
      for each tuple:

      * field name
      * model name
      * SQL table name: Put `False` if the model is already loaded in the
        registry and thus the SQL table name can be obtained that way.
      * field type: binary, boolean, char, date, datetime, float, html,
        integer, many2many, many2one, monetary, one2many, reference,
        selection, text, serialized. The list can vary depending on Odoo
        version or custom added field types.
      * SQL field type: If the field type is custom or it's one of the special
        cases (see below), you need to indicate here the SQL type to use
        (from the valid PostgreSQL types):
        https://www.postgresql.org/docs/9.6/static/datatype.html
      * module name: for adding the XML-ID entry.
      * (optional) initialization value: if included in the tuple, it is set
        in the column for existing records.
    """
    sql_type_mapping = {
        'binary': 'bytea',  # If there's attachment, no SQL. Force it manually
        'boolean': 'bool',
        'char': 'varchar',  # Force it manually if there's size limit
        'date': 'date',
        'datetime': 'timestamp',
        'float': 'numeric',  # Force manually to double precision if no digits
        'html': 'text',
        'integer': 'int4',
        'many2many': False,  # No need to create SQL column
        'many2one': 'int4',
        'monetary': 'numeric',
        'one2many': False,  # No need to create SQL column
        'reference': 'varchar',
        'selection': 'varchar',  # Can be sometimes integer. Force it manually
        'text': 'text',
        'serialized': 'text',
    }
    for vals in field_spec:
        field_name = vals[0]
        model_name = vals[1]
        table_name = vals[2]
        field_type = vals[3]
        sql_type = vals[4]
        module = vals[5]
        init_value = vals[6] if len(vals) > 6 else False
        # Add SQL column
        if not table_name:
            table_name = env[model_name]._table
        if not column_exists(env.cr, table_name, field_name):
            sql_type = sql_type or sql_type_mapping.get(field_type)
            if sql_type:
                query = sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                    sql.Identifier(table_name),
                    sql.Identifier(field_name),
                    sql.SQL(sql_type),
                )
                args = []
                if init_value:
                    query += sql.SQL(" DEFAULT %s")
                    args.append(init_value)
                logged_query(env.cr, query, args)
                if init_value:
                    logged_query(env.cr, sql.SQL(
                        "ALTER TABLE {} ALTER COLUMN {} DROP DEFAULT").format(
                            sql.Identifier(table_name),
                            sql.Identifier(field_name),
                        )
                    )
        # Add ir.model.fields entry
        env.cr.execute(
            "SELECT id FROM ir_model WHERE model = %s", (model_name, ),
        )
        row = env.cr.fetchone()
        if not row:
            continue
        model_id = row[0]
        env.cr.execute(
            "SELECT id FROM ir_model_fields "
            "WHERE model_id = %s AND name = %s",
            (model_id, field_name)
        )
        row = env.cr.fetchone()
        field_id = row and row[0] or False
        if field_id:
            logger.warning(
                "add_fields: There's already an entry for %s in %s. This may "
                "mean that there's some misconfiguration, or simply that "
                "another module added the same field previously." % (
                    field_name, model_name,
                )
            )
        else:
            # `select_level` is required in ir.model.fields for Odoo <= v8
            extra_cols = extra_placeholders = sql.SQL("")
            if version_info < (9, 0):
                extra_cols = sql.SQL(", select_level")
                extra_placeholders = sql.SQL(", %(select_level)s")
            logged_query(
                env.cr,
                sql.SQL(
                    """
                    INSERT INTO ir_model_fields (
                        model_id, model, name, field_description,
                        ttype, state{extra_cols}
                    ) VALUES (
                        %(model_id)s, %(model)s, %(name)s,
                        %(field_description)s, %(ttype)s,
                        %(state)s{extra_placeholders}
                    ) RETURNING id
                    """
                ).format(
                    extra_cols=extra_cols,
                    extra_placeholders=extra_placeholders,
                ),
                {
                    "model_id": model_id,
                    "model": model_name,
                    "name": field_name,
                    "field_description": "OU",
                    "ttype": field_type,
                    "state": "base",
                    "select_level": "0",
                },
            )
            field_id = env.cr.fetchone()[0]
        # Add ir.model.data entry
        if not module or version_info[0] >= 12:
            continue
        name1 = 'field_%s_%s' % (model_name.replace('.', '_'), field_name)
        try:
            with env.cr.savepoint():
                logged_query(
                    env.cr, """
                    INSERT INTO ir_model_data (
                        name, date_init, date_update, module, model, res_id
                    ) VALUES (
                        %s, (now() at time zone 'UTC'),
                        (now() at time zone 'UTC'), %s, %s, %s
                    )""", (name1, module, 'ir.model.fields', field_id),
                )
        except IntegrityError:
            # Do not fail if already present
            pass


def update_field_multilang(records, field, method):
    """Update a field in all available languages in the database.

    :param records:
        Recordset to be updated.

    :param str field:
        Field to be updated.

    :param callable method:
        Method to execute to update the field.

        It will be called with: ``(old_value, lang_code, record)``
    """
    installed_langs = [(records.env.lang or "en_US", "English")]
    if records._fields[field].translate:
        installed_langs = records.env["res.lang"].get_installed()
    for lang_code, lang_name in installed_langs:
        for record in records.with_context(lang=lang_code):
            new_value = method(record[field], lang_code, record)
            if record[field] != new_value:
                record[field] = new_value


def update_module_moved_fields(
        cr, model, moved_fields, old_module, new_module):
    """Update module for field definition in general tables that have been
    moved from one module to another.

    No need to use this method: moving the XMLID is covered in
    Odoo and OpenUpgrade natively.

    :param cr: Database cursor
    :param model: model name
    :param moved_fields: list of moved fields
    :param old_module: previous module of the fields
    :param new_module: new module of the fields
    """
    if version_info[0] <= 7:
        do_raise("This only works for Odoo version >=v8")
    if not isinstance(moved_fields, (list, tuple)):
        do_raise("moved_fields %s must be a tuple or list!" % moved_fields)
    logger.info(
        "Moving fields %s in model %s from module '%s' to module '%s'",
        ', '.join(moved_fields), model, old_module, new_module,
    )
    vals = {
        'new_module': new_module,
        'old_module': old_module,
        'model': model,
        'fields': tuple(moved_fields),
    }
    # update xml-id entries
    logged_query(
        cr, """
        UPDATE ir_model_data imd
        SET module = %(new_module)s
        FROM ir_model_fields imf
        WHERE
            imf.model = %(model)s AND
            imf.name IN %(fields)s AND
            imd.module = %(old_module)s AND
            imd.model = 'ir.model.fields' AND
            imd.res_id = imf.id AND
            imd.id NOT IN (
               SELECT id FROM ir_model_data WHERE module = %(new_module)s
            )
        """, vals,
    )
    # update ir_translation - it covers both <=v8 through type='field' and
    # >=v9 through type='model' + name
    logged_query(
        cr, """
        UPDATE ir_translation it
        SET module = %(new_module)s
        FROM ir_model_fields imf
        WHERE
            imf.model = %(model)s AND
            imf.name IN %(fields)s AND
            it.res_id = imf.id AND
            it.module = %(old_module)s AND ((
                it.name LIKE 'ir.model.fields,field_%%' AND
                it.type = 'model'
            ) OR (
                it.type = 'field'
            ))
        """, vals,
    )


def safe_unlink(records, do_raise=False):
    """Allow for errors to occur during unlinking of records.

    Prevent broken database transactions, and by default, catch exceptions.

    :param records: an iterable (not necessarily recordset) of records to
        unlink.
    :param do_raise: when set to True, don't catch exceptions but let them
        be raised.
    """
    for record in records:
        logger.debug("Deleting record %s#%s", record._name, record.id)
        if not record.exists():
            continue
        try:
            with record.env.cr.savepoint():
                record.unlink()
        except Exception as e:
            if do_raise:
                raise
            logger.info("Error deleting %s#%s: %s",
                        record._name, record.id, repr(e))


def delete_records_safely_by_xml_id(env, xml_ids):
    """This removes in the safest possible way the records whose XML-IDs are
    passed as argument.

    :param xml_ids: List of XML-ID string identifiers of the records to remove.
    """
    for xml_id in xml_ids:
        logger.debug('Deleting record for XML-ID %s', xml_id)
        try:
            # This can raise an environment KeyError if the model is not loaded
            record = env.ref(xml_id, raise_if_not_found=False)
            if not record:
                continue
            safe_unlink(record, do_raise=True)
        except Exception as e:
            logger.info('Error deleting XML-ID %s: %s', xml_id, repr(e))


def chunked(records, single=True):
    """ Memory and performance friendly method to iterate over a potentially
    large number of records. Yields either a whole chunk or a single record
    at the time. Don't nest calls to this method. """
    if version_info[0] > 10:
        invalidate = records.env.cache.invalidate
    elif version_info[0] > 7:
        invalidate = records.env.invalidate_all
    else:
        raise Exception('Not supported Odoo version for this method.')
    size = core.models.PREFETCH_MAX
    model = records._name
    ids = records.with_context(prefetch_fields=False).ids
    for i in range(0, len(ids), size):
        invalidate()
        chunk = records.env[model].browse(ids[i:i + size])
        if single:
            for record in chunk:
                yield record
            continue
        yield chunk


def set_xml_ids_noupdate_value(env, module, xml_ids, value):
    """Set the xml_ids noupdate values in a module.

    :param module: module name
    :param xml_ids: a tuple or list of xml record IDs
    :param bool value: True or False.
    """
    if not isinstance(xml_ids, (list, tuple)):
        do_raise("XML IDs %s must be a tuple or list!" % xml_ids)

    logged_query(env.cr, """
        UPDATE ir_model_data
        SET noupdate = %s
        WHERE module = %s AND name in %s
    """, (value, module, tuple(xml_ids),))


def convert_to_company_dependent(
    env,
    model_name,
    origin_field_name,
    destination_field_name,
    model_table_name=None,
):
    """ For each row in a given table, the value of a given field is
    set in another 'company dependant' field of the same table.
    Useful in cases when from one version to another one, some field in a
    model becomes a 'company dependent' field.

    This method must be executed in post-migration scripts after
    the field is created, or in pre-migration if you have previously
    executed add_fields openupgradelib method.

    :param model_name: Name of the model.
    :param origin_field_name: Name of the field from which the values
      will be obtained.
    :param destination_field_name: Name of the 'company dependent'
      field where the values obtained from origin_field_name will be set.
    :param model_table_name: Name of the table. Optional. If not provided
      the table name is taken from the model (so the model must be
      registered previously).
    """
    logger.debug("Converting {} in {} to company_dependent field {}.".format(
        origin_field_name, model_name, destination_field_name))
    if origin_field_name == destination_field_name:
        do_raise("A field can't be converted to property without changing "
                 "its name.")
    cr = env.cr
    mapping_type2field = {
        'char': 'value_text',
        'float': 'value_float',
        'boolean': 'value_integer',
        'integer': 'value_integer',
        'text': 'value_text',
        'binary': 'value_binary',
        'many2one': 'value_reference',
        'date': 'value_datetime',
        'datetime': 'value_datetime',
        'selection': 'value_text',
    }
    # Determine field id, field type and the model name of the relation
    # in case of many2one.
    cr.execute("SELECT id, relation, ttype FROM ir_model_fields "
               "WHERE name=%s AND model=%s",
               (destination_field_name, model_name))
    destination_field_id, relation, d_field_type = cr.fetchone()
    value_field_name = mapping_type2field.get(d_field_type)
    field_select = sql.Identifier(origin_field_name)
    args = {
        'model_name': model_name,
        'fields_id': destination_field_id,
        'name': destination_field_name,
        'type': d_field_type,
    }
    if d_field_type == 'many2one':
        field_select = sql.SQL("%(relation)s || ',' || {}::TEXT").format(
            sql.Identifier(origin_field_name))
        args['relation'] = relation
    elif d_field_type == 'boolean':
        field_select = sql.SQL("CASE WHEN {} = true THEN 1 ELSE 0 END").format(
            sql.Identifier(origin_field_name))
    cr.execute("SELECT id FROM res_company")
    company_ids = [x[0] for x in cr.fetchall()]
    for company_id in company_ids:
        args['company_id'] = company_id
        logged_query(
            cr, sql.SQL("""
            INSERT INTO ir_property (
                fields_id, company_id, res_id, name, type, {value_field_name}
            )
            SELECT
                %(fields_id)s, %(company_id)s,
                %(model_name)s || ',' || id::TEXT, %(name)s,
                %(type)s, {field_select}
            FROM {table_name} WHERE {origin_field_name} IS NOT NULL;
            """).format(
                value_field_name=sql.Identifier(value_field_name),
                field_select=field_select,
                origin_field_name=sql.Identifier(origin_field_name),
                table_name=sql.Identifier(
                    model_table_name or env[model_name]._table
                )
            ), args,
        )


def cow_templates_mark_if_equal_to_upstream(cr, mark_colname=None):
    """Record which COW'd templates are equal to their upstream equivalents.

    This is meant to be executed in a pre-migration script.

    This only makes sense if:

    1. Origin is >= v12.
    2. Website was installed. Hint: run this in website's pre-migration.
    3. You are going to run :func:`cow_templates_replicate_upstream` in the
       end-migration.
    """
    mark_colname = mark_colname or get_legacy_name("cow_equal_to_upstream")
    mark_identifier = sql.Identifier(mark_colname)
    if not column_exists(cr, "ir_ui_view", mark_colname):
        logged_query(
            cr,
            sql.SQL("ALTER TABLE ir_ui_view ADD COLUMN {} BOOLEAN")
            .format(mark_identifier))
    # Map all qweb views
    cr.execute("""
        SELECT id, arch_db, key, website_id
        FROM ir_ui_view
        WHERE type = 'qweb' AND key IS NOT NULL
    """)
    views_map = {}
    for id_, arch_db, key, website_id in cr.fetchall():
        views_map[(key, website_id)] = (id_, arch_db)
    # Detect website-specific views COW'd without alterations from upstream
    equal = []
    for (key, website_id), (id_, arch_db) in views_map.items():
        if not website_id:
            # Skip upstream views
            continue
        try:
            upstream_arch = views_map[(key, None)][1]
        except KeyError:
            # Skip website-specific views that have no upstream equivalent
            continue
        # It seems that, when you just use the `customize_show` widget without
        # ever touching the view, the COW system duplicates `arch_db`
        # preserving even the same whitespace.
        # In case this is proven false under some circumstances, we would need
        # to do a smarter XML comparison here.
        if arch_db == upstream_arch:
            equal.append(id_)
    # Mark equal views
    logged_query(
        cr,
        sql.SQL("UPDATE ir_ui_view SET {} = TRUE WHERE id = ANY(%s)")
        .format(mark_identifier),
        (equal,),
    )


def cow_templates_replicate_upstream(cr, mark_colname=None):
    """Reset COW'd templates to their upstream equivalents.

    This is meant to be executed in an end-migration script.

    This only makes sense if:

    1. Origin is >= v12.
    2. Website was installed. Hint: run this in website's end-migration.
    3. You ran :func:`cow_templates_mark_if_equal_to_upstream` in the
       pre-migration.
    """
    mark_colname = mark_colname or get_legacy_name("cow_equal_to_upstream")
    mark_identifier = sql.Identifier(mark_colname)
    logged_query(
        cr,
        sql.SQL("""
            UPDATE ir_ui_view AS specific
            SET arch_db = generic.arch_db
            FROM ir_ui_view AS generic
            WHERE
                specific.{} IS NOT NULL AND
                specific.website_id IS NOT NULL AND
                generic.website_id IS NULL AND
                specific.key = generic.key AND
                specific.type = 'qweb' AND
                generic.type = 'qweb'
        """)
        .format(mark_identifier),
    )
