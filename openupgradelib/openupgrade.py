# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    This module copyright (C) 2011-2013 Therp BV (<http://therp.nl>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import sys
import os
import inspect
import uuid
import logging
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO
from contextlib import contextmanager
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

from psycopg2.extensions import AsIs
from lxml import etree
from . import openupgrade_tools

core = None
# The order matters here. We can import odoo in 9.0, but then we get odoo.py
try:  # < 10.0
    import openerp as core
    from openerp.modules import registry as RegistryManager
except ImportError:  # >= 10.0
    import odoo as core
    from odoo.modules import registry as RegistryManager
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
    yaml_import = tools.yaml_import

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
else:
    # version < 6.1
    import tools
    SUPERUSER_ID = 1
    from tools.yaml_import import yaml_import
    from osv.osv import except_osv as except_orm
    RegistryManager = None
    from osv.fields import many2many, one2many


def do_raise(error):
    if UserError:
        raise UserError(error)
    raise except_orm('Error', error)

if sys.version_info[0] == 3:
    unicode = str

if version_info[0] > 7:
    api = core.api


# The server log level has not been set at this point
# so to log at loglevel debug we need to set it
# manually here. As a consequence, DEBUG messages from
# this file are always logged
logger = logging.getLogger('OpenUpgrade')
logger.setLevel(logging.DEBUG)

__all__ = [
    'migrate',
    'logging',
    'load_data',
    'copy_columns',
    'rename_columns',
    'rename_fields',
    'rename_tables',
    'rename_models',
    'rename_xmlids',
    'add_xmlid',
    'drop_columns',
    'delete_model_workflow',
    'update_workflow_workitems',
    'warn_possible_dataloss',
    'set_defaults',
    'logged_query',
    'column_exists',
    'table_exists',
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
        from psycopg2 import errorcodes, ProgrammingError
    except ImportError:
        from psycopg2cffi import errorcodes, ProgrammingError

    try:
        with cr.savepoint():
            yield
    except ProgrammingError as error:
        msg = "Code: {code}. Class: {class_}. Error: {error}.".format(
            code=error.pgcode,
            class_=errorcodes.lookup(error.pgcode[:2]),
            error=errorcodes.lookup(error.pgcode))
        if error.pgcode not in codes and error.pgcode[:2] in codes:
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
    directory.
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
    fp = tools.file_open(pathname)
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
            yield StringIO(etree.tostring(path))
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
            cr.execute('DROP INDEX IF EXISTS "%s_%s_index"' % (table, old))


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
    :param fields_spec: a list of tuples with the following elements:
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
                "%s,%s" % (model, old_field),
                "%s,%s" % (model, new_field),
            ),
        )
        # Rename appearances on export profiles
        # TODO: Rename when the field is part of a submodel (ex. m2one.field)
        cr.execute("""
            UPDATE ir_exports_line
            SET name = %s
            WHERE name = %s
            """, (old_field, new_field),
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
        cr.execute('UPDATE ir_model SET model = %s '
                   'WHERE model = %s', (new, old,))
        cr.execute('UPDATE ir_model_fields SET relation = %s '
                   'WHERE relation = %s', (new, old,))
        cr.execute('UPDATE ir_model_data SET model = %s '
                   'WHERE model = %s', (new, old,))
        cr.execute('UPDATE ir_attachment SET res_model = %s '
                   'WHERE res_model = %s', (new, old,))
        cr.execute('UPDATE ir_model_fields SET model = %s '
                   'WHERE model = %s', (new, old,))
        cr.execute('UPDATE ir_translation set '
                   "name=%s || substr(name, strpos(name, ',')) "
                   'where name like %s',
                   (new, old + ',%'),)
        if is_module_installed(cr, 'mail'):
            # fortunately, the data model didn't change up to now
            cr.execute(
                'UPDATE mail_message SET model=%s where model=%s', (new, old),
            )
            if table_exists(cr, 'mail_followers'):
                cr.execute(
                    'UPDATE mail_followers SET res_model=%s '
                    'where res_model=%s',
                    (new, old),
                )

    # TODO: signal where the model occurs in references to ir_model


def rename_xmlids(cr, xmlids_spec):
    """
    Rename XML IDs. Typically called in the pre script.
    One usage example is when an ID changes module. In OpenERP 6 for example,
    a number of res_groups IDs moved to module base from other modules (
    although they were still being defined in their respective module).

    :param xmlids_spec: a list of tuples (old module.xmlid, new module.xmlid).
    """
    for (old, new) in xmlids_spec:
        if '.' not in old or '.' not in new:
            logger.error(
                'Cannot rename XMLID %s to %s: need the module '
                'reference to be specified in the IDs' % (old, new))
        else:
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
        logged_query(
            cr,
            "INSERT INTO ir_model_data (create_uid, create_date, "
            "write_uid, write_date, date_init, date_update, noupdate, "
            "name, module, model, res_id) "
            "VALUES (%s, (now() at time zone 'UTC'), %s, "
            "(now() at time zone 'UTC'), (now() at time zone 'UTC'), "
            "(now() at time zone 'UTC'), %s, %s, %s, %s, %s)", (
                SUPERUSER_ID, SUPERUSER_ID, noupdate,
                xmlid, module, model, res_id))
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


def delete_model_workflow(cr, model):
    """
    Forcefully remove active workflows for obsolete models,
    to prevent foreign key issues when the orm deletes the model.
    """
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

    :param pool: In v10 and newer, you have to pass the 'env' instead.
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
            for res_id in ids:
                # Iterating over ids here as a workaround for lp:1131653
                if version_info[0] >= 8:
                    obj.write({field: value})
                else:
                    obj.write(cr, SUPERUSER_ID, [res_id], {field: value})
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
        if version_info[0] >= 8:
            obj = pool.get(model, False)
        else:
            obj = pool.get(model)
            if not obj or obj == False: ## is this the same: obj not vs obj false?
                do_raise(
                    "Migration: error setting default, no such model: %s" % model)
                    
        for field, value in default_spec[model]:
            domain = not force and [(field, '=', False)] or []
            if version_info[0] > 8:
                ids = obj.search(domain).ids
            else:
                ids = obj.search(cr, SUPERUSER_ID, domain)
            if not ids:
                continue
            if value is None:
                # Set the value by calling the _defaults of the object.
                # Typically used for company_id on various models, and in that
                # case the result depends on the user associated with the
                # object. We retrieve create_uid for this purpose and need to
                # call the defaults function per resource. Otherwise, write
                # all resources at once.
                if version_info[0] > 7:
                    if obj.default_get([field]):
                        write_value(ids, field, obj.default_get([field]))
                    else:
                        cr.execute(
                            "SELECT id, COALESCE(create_uid, 1) FROM %s " %
                            obj._table + "WHERE id in %s", (tuple(ids),))
                        # Execute the function once per user_id
                        user_id_map = {}
                        for row in cr.fetchall():
                            user_id_map.setdefault(row[1], []).append(row[0])
                        for user_id in user_id_map:
                            write_value(
                                user_id_map[user_id], field,
                                obj.default_get([field])(
                                    obj, cr, user_id, None))
                else:
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


def logged_query(cr, query, args=None):
    """
    Logs query and affected rows at level DEBUG.

    :param query: a query string suitable to pass to cursor.execute()
    :param args: a list, tuple or dictionary passed as substitution values \
to cursor.execute().
    """
    if args is None:
        args = ()
    args = tuple(args) if type(args) == list else args
    cr.execute(query, args)
    logger.debug('Running %s', query % args)
    logger.debug('%s rows affected', cr.rowcount)
    return cr.rowcount


def update_module_names(cr, namespec, merge_modules=False):
    """Deal with changed module names, making all the needed changes on the
    related tables, like XML-IDs, translations, and so on.

    :param namespec: list of tuples of (old name, new name)
    :param merge_modules: Specify if the operation should be a merge instead
        of just a renaming.
    """
    for (old_name, new_name) in namespec:
        if merge_modules:
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
                 "module = %s"
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
        data_obj = RegistryManager.get(cr.dbname)['ir.model.data']
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
                except Exception as e:
                    logger.error(
                        "'migrate' decorator: failed to inspect "
                        "the frame above: %s" % e)
                    pass
                if not version and not no_version:
                    return
                logger.info(
                    "%s: %s-migration script called with version %s" %
                    (module, stage, version))
                try:
                    # The actual function is called here
                    func(
                        api.Environment(
                            cr, uid or SUPERUSER_ID, context or {})
                        if use_env2 else cr, version)
                except Exception as e:
                    message = repr(e) if sys.version_info[0] == 2 else str(e)
                    logger.error(
                        "%s: error in migration script %s: %s",
                        module, filename, message)
                    logger.exception(e)
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
        }
        logged_query(
            cr,
            """
            UPDATE %(table_name)s my_table
            SET %(datetime_field_name)s =
                my_table.%(date_field_name)s::TIMESTAMP AT TIME ZONE 'UTC'
            FROM res_partner rp, res_users ru
            WHERE my_table.%(date_field_name)s IS NOT NULL
                AND my_table.user_id=ru.id
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
        except:
            cr.execute('ROLLBACK TO SAVEPOINT "%s"' % name)


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
    try:
        from odoo.tools.safe_eval import safe_eval
    except ImportError:
        from openerp.tools.safe_eval import safe_eval
    import time
    try:
        basetring
    except:  # For Python 3 compatibility
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
        context = safe_eval(f.context, {'time': time, 'uid': env.uid})
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
