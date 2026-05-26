import os
import unittest
from io import StringIO
from unittest import mock

import psycopg2

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

    def test_chunked(self):
        records = self.env["ir.module.module"].search([])

        chunked_records = self.env["ir.module.module"]
        for chunk in openupgrade.chunked(records):
            chunked_records += chunk
        self.assertEqual(records, chunked_records)

        chunked_records = self.env["ir.module.module"]
        for chunk in openupgrade.chunked(records, single=True):
            chunked_records += chunk
        self.assertEqual(records, chunked_records)

    def test_rename_field_references(self):
        test_filter = self.env["ir.filters"].create(
            {
                "name": "test filter",
                "model_id": "ir.module.module",
                "domain": "[('name', '=', 'test')]",
            }
        )
        openupgrade.rename_field_references(
            self.env,
            [("ir.module.module", "name", "renamed_name")],
        )
        openupgrade.openupgrade_tools.invalidate_cache(self.env, flush=True)
        self.assertEqual(test_filter.domain, "[('renamed_name', '=', 'test')]")

    def test_lift_constraints(self):
        self.env.cr.execute("SAVEPOINT test")
        with self.assertRaises(psycopg2.errors.DependentObjectsStillExist):
            openupgrade.lift_constraints(
                self.env.cr,
                "res_partner",
                "id",
            )
        self.env.cr.execute("ROLLBACK TO SAVEPOINT test")
        self.env.cr.execute("SAVEPOINT test")
        admin_partner = self.env.ref("base.user_admin").partner_id
        with self.assertRaises(psycopg2.errors.ForeignKeyViolation):
            self.env.cr.execute(
                "DELETE FROM res_partner WHERE id=%s", (admin_partner.id,)
            )
        self.env.cr.execute("ROLLBACK TO SAVEPOINT test")
        self.env.cr.execute("SAVEPOINT test")
        openupgrade.lift_constraints(
            self.env.cr,
            "res_partner",
            "id",
            cascade=True,
        )
        self.env.cr.execute("DELETE FROM res_partner WHERE id=%s", (admin_partner.id,))
        self.assertFalse(admin_partner.exists())
        self.env.cr.execute("ROLLBACK TO SAVEPOINT test")

    def test_load_data(self):
        admin_user = self.env.ref("base.user_admin")

        def patched_file_open(path, *args, **kwargs):
            if path == "dummy_module/dummy.xml":
                result = StringIO(
                    """
                    <odoo>
                        <record id="base.user_admin" model="res.users">
                            <field name="name">Not Administrator</field>
                            <field name="signature">changed signature</field>
                        </record>
                    </odoo>
                    """
                )
            elif path == "dummy_module/dummy-transformation.xml":
                result = StringIO(
                    """
                    <odoo>
                        <xpath expr="//field[@name='name']" position="replace" />
                    </odoo>
                    """
                )
            elif path == "dummy_module/dummy-transformation2.xml":
                result = StringIO(
                    """
                    <odoo>
                        <xpath expr="//field[@name='name']" position="replace" />
                        <xpath expr="//field[@name='signature']" position="replace" />
                    </odoo>
                    """
                )
            result.name = "dummy.xml"
            return result

        env_or_cr = self.env if openupgrade.version_info[0] > 16 else self.cr

        with mock.patch("odoo.tools.file_open") as file_open:
            file_open.side_effect = patched_file_open

            openupgrade.load_data(env_or_cr, "dummy_module", "dummy.xml")
            self.assertEqual(admin_user.name, "Not Administrator")
            self.assertIn("changed signature", admin_user.signature)

            admin_user.name = "Administrator"
            admin_user.signature = "original signature"
            openupgrade.load_data(
                env_or_cr,
                "dummy_module",
                "dummy.xml",
                xml_transformation_filename="dummy-transformation.xml",
            )
            self.assertEqual(admin_user.name, "Administrator")
            self.assertIn("changed signature", admin_user.signature)

            admin_user.signature = "original signature"
            openupgrade.load_data(
                env_or_cr,
                "dummy_module",
                "dummy.xml",
                xml_transformation_filename="dummy-transformation2.xml",
            )
            self.assertEqual(admin_user.name, "Administrator")
            self.assertIn("original signature", admin_user.signature)

    def tearDown(self):
        super().tearDown()
        self.cr.close()
