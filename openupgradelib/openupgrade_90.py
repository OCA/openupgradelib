# -*- coding: utf-8 -*-
# Copyright 2017 Tecnativa - Pedro M. Baeza <pedro.baeza@tecnativa.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""This module provides simple tools for OpenUpgrade migration, specific for
the 8.0 -> 9.0 migration.
"""
import logging
import threading

from psycopg2.extensions import AsIs

from openupgradelib import openupgrade


def convert_binary_field_to_attachment(env, field_spec):
    """This method converts the 8.0 binary fields to attachments like Odoo 9.0
    makes with the new attachment=True attribute. It has to be called on
    post-migration script, as there's a call to get the res_name of the
    target model, which is not yet loaded on pre-migration.

    You need to rename the involved column in pre-migration script if you
    don't want to lose your data in the process.

    This method also removes after the conversion the source column for
    avoiding data duplication.

    This is done through Odoo ORM, because there's a lot of logic associated
    with guessing MIME type, format and length, file saving in store...
    that is doesn't worth to recreate it via SQL as there's not too much
    performance problem.

    :param env: Odoo environment
    :param field_spec: A dictionary with the ORM model name as key, and as
        dictionary values a tuple with:

        * field name to be converted as attachment as first element.
        * SQL column name that contains actual data as second element. If
          the second element is None, then the column name is taken
          calling `get_legacy_name` method, which is the typical technique.
    """
    logger = logging.getLogger('OpenUpgrade')
    attachment_model = env['ir.attachment']
    for model_name in field_spec:
        model = env[model_name]
        for field, column in field_spec[model_name]:
            if column is None:
                column = openupgrade.get_legacy_name(field)
            logger.info(
                "Converting to attachment field {} from model {} stored in "
                "column {}".format(field, model_name, column)
            )
            last_id = 0
            while True:
                env.cr.execute(
                    """SELECT id, {0} FROM {1} WHERE {0} IS NOT NULL AND id > {2}
                    ORDER BY id LIMIT 500;
                    """.format(column, model._table, last_id)
                )
                rows = env.cr.fetchall()
                if not rows:
                    break
                logger.info(
                    "  converting {0} items starting after {1}..."
                    "".format(len(rows), last_id))
                for row in rows:
                    last_id = row[0]
                    data = bytes(row[1])
                    if data and data != 'None':
                        attachment_model.create({
                            'name': field,
                            'res_model': model_name,
                            'res_field': field,
                            'res_id': last_id,
                            'type': 'binary',
                            'datas': data,
                        })
            # Remove source column for cleaning the room
            env.cr.execute("ALTER TABLE {} DROP COLUMN {}".format(
                model._table, column,
            ))


def replace_account_types(env, type_spec, unlink=True):
    """ Replace old account types with their replacements. The old account
    type is allowed not to exist anymore, except when running unit tests.
    :param type_spec: list of tuples (xmlid of old account.account.type, \
xmlid of new account.account.type)
    :param unlink: attempt to unlink the old account type
    """
    logger = logging.getLogger('OpenUpgrade')
    for old_type, new_type in type_spec:
        try:
            type8 = env.ref(old_type)
        except ValueError:
            if getattr(threading.currentThread(), 'testing', False):
                raise
            continue

        type9 = env.ref(new_type)
        for table in ('account_account',
                      'account_account_template',
                      'account_move_line'):
            env.cr.execute(
                "UPDATE %s SET user_type_id = %s WHERE user_type_id = %s",
                (AsIs(table), type9.id, type8.id))
        if unlink:
            with env.cr.savepoint():
                try:
                    type8.unlink()
                except Exception as e:
                    logger.info(
                        'Could not remove account type %s: %s',
                        old_type, e)
