from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.set_defaults(
        env.cr, env, {'res.partner': [('active', None)]}, force=True)
    openupgrade.set_defaults(
        env.cr, env, {'res.partner': [('active', None)]}, force=True,
        use_orm=True)
