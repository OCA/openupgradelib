# coding: utf-8
from openerp import pooler
from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(cr, version):
    pool = pooler.get_pool(cr.dbname)
    # Set the default for res.partner 'active' column to True instead of 1
    # which breaks the SQL method of set_defaults
    pool['res.partner']._defaults['active'] = lambda *args: True
    openupgrade.set_defaults(
        cr, pool, {'res.partner': [('active', None)]}, force=True)
    openupgrade.set_defaults(
        cr, pool, {'res.partner': [('active', None)]}, force=True,
        use_orm=True)
