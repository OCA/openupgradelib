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

import logging
from .openupgrade import column_exists
# from .openupgrade import version_info

logger = logging.getLogger('OpenUpgradeCleanup')
logger.setLevel(logging.DEBUG)

###########################################
#
# NOTE: Please try to homologate this library with
# database_cleanup module as you contribute
# You can find it here:
# https://github.com/OCA/server-tools/tree/9.0/database_cleanup
#
# Feel yourself encouraged to contact the author of a
# similar method in databse_cleanup (git blame).
#
###########################################


__all__ = [
    'drop_m2m_table',
    'drop_columns',
]


def drop_m2m_table(env, table_spec):
    """
    Drop a many2many relation table properly.
    You will typically want to use it in post-migration scripts after you \
    have migrated the values of your many2many fields.

    :param cr: The database cursor
    :param table_spec: list of strings ['table one', 'table two']

    .. versionadded:: 9.0
    """
    drop = env['ir.model.relation']._module_data_uninstall
    for table in table_spec:
        query = """SELECT id FROM ir_model_relation
                   WHERE name='{0}'""".format(table)
        env.cr.execute(query)
        ids = [x[0] for x in env.cr.fetchall()]
        drop(ids)


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
