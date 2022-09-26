# Copyright 2022 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""This module provides simple tools for OpenUpgrade migration, specific for
the >=16.0 migration.
"""
import itertools
from .openupgrade import logged_query, table_exists
from odoo.tools.translate import _get_translation_upgrade_queries


def migrate_translations_to_jsonb(env, fields_spec):
    """
    In Odoo 16, translated fields no longer use the model ir.translation.
    Instead they store all their values into jsonb columns
    in the model's table.
    See https://github.com/odoo/odoo/pull/97692 for more details.

    Odoo provides a method _get_translation_upgrade_queries returning queries
    to execute to migrate all the translations of a particular field.

    The present openupgrade method executes the provided queries
    on table _ir_translation if exists (when ir_translation table was renamed
    by Odoo's migration scripts) or on table ir_translation (if module was
    migrated by OCA).

    This should be called in a post-migration script of the module
    that contains the definition of the translatable field.

    :param fields_spec: list of tuples of (model name, field name)
    """
    initial_translation_tables = None
    if table_exists(env.cr, "_ir_translation"):
        initial_translation_tables = "_ir_translation"
    elif table_exists(env.cr, "ir_translation"):
        initial_translation_tables = "ir_translation"
    if initial_translation_tables:
        for model, field_name in fields_spec:
            field = env[model]._fields[field_name]
            for query in itertools.chain.from_iterable(
                _get_translation_upgrade_queries(env.cr, field)
            ):
                if initial_translation_tables == "ir_translation":
                    query = query.replace("_ir_translation", "ir_translation")
                logged_query(env.cr, query)
