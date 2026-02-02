import os
import unittest

import odoo

# needs to be imported after Odoo initialized, done in test setup
openupgrade = None


class TestOpenupgradelib(unittest.TestCase):
    """
    Test openupgradelib
    """

    def setUp(self):
        global openupgrade
        super().setUp()

        # < v19
        registry = getattr(odoo, "registry", None)
        if not registry:
            # >= v19
            __import__("odoo", fromlist=["orm"])
            orm = __import__("odoo.orm", fromlist=["registry"])
            registry = orm.registry.Registry

        self.registry = registry(os.environ.get("PGDATABASE"))
        self.cr = self.registry.cursor()
        self.env = odoo.api.Environment(self.cr, odoo.SUPERUSER_ID, {})
        openupgradelib = __import__("openupgradelib", fromlist=["openupgrade"])
        openupgrade = openupgradelib.openupgrade

    def test_migrate_env(self):
        @openupgrade.migrate(use_env=False)
        def migrate_with_cr(cr, version):
            self.assertTrue(isinstance(cr, odoo.sql_db.Cursor))

        @openupgrade.migrate(use_env=True)
        def migrate_with_env(env, version):
            self.assertTrue(isinstance(env, odoo.api.Environment))

        migrate_with_cr(self.cr, "irrelevant.version")
        migrate_with_env(self.cr, "irrelevant.version")

    def test_delete_translations(self):
        record = self.env.ref("base.module_base")

        self.assertNotEqual(
            record.with_context(lang="en_US").description,
            record.with_context(lang="fr_FR").description,
        )

        openupgrade.delete_record_translations(self.cr, "base", ["module_base"])

        invalidate_func = getattr(
            record,
            "invalidate_recordset",
            getattr(record, "invalidate_cache", lambda *args: None),
        )
        invalidate_func()

        self.assertEqual(
            record.with_context(lang="en_US").description,
            record.with_context(lang="fr_FR").description,
        )

    def tearDown(self):
        super().tearDown()
        self.cr.close()
