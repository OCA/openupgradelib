# coding: utf-8
from openerp import pooler
from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(cr, version):
    pool = pooler.get_pool(cr.dbname)
    openupgrade.set_defaults(
        cr, pool, {'res.partner': [('active', None)]}, force=True)
    openupgrade.set_defaults(
        cr, pool, {'res.partner': [('active', None)]}, force=True,
        use_orm=True)
