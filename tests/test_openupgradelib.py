import json
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

    def test_disable_invalid_filters(self):
        invalid_filter = self.env["ir.filters"].create(
            {
                "name": "Invalid filter",
                "domain": "[('nonexisting_field', '=', True)]",
                "model_id": "res.partner",
            }
        )
        self.assertTrue(invalid_filter.active)
        openupgrade.disable_invalid_filters(self.env)
        self.assertFalse(invalid_filter.active)
        invalid_filter.active = True
        for field in ("user_id", "user_ids"):
            if field in invalid_filter._fields:
                invalid_filter[field] = self.env.ref("base.user_admin")
        openupgrade.disable_invalid_filters(self.env)
        self.assertFalse(invalid_filter.active)

    def test_update_module_names(self):
        old = "dummy_module"
        new = "renamed_module"
        Mod = self.env["ir.module.module"]
        # Dummy module is installed
        Mod.update_list()
        dummy_module = Mod.search([("name", "=", old)])
        self.assertTrue(dummy_module, "Dummy module not found")
        dummy_module.button_immediate_install()
        self.assertEqual(dummy_module.state, "installed", "Dummy module not installed")
        # Rename dummy module using namespec
        openupgrade.update_module_names(self.cr, {old: new}.items())
        dummy_module = Mod.search([("name", "=", old)])
        renamed_module = Mod.search([("name", "=", new)])
        self.assertFalse(dummy_module)
        self.assertTrue(renamed_module)
        # Ensure invalid JSON raises an error
        with mock.patch.dict(
            os.environ,
            {"OPENUPGRADE_RENAMED_MODULES": "Invalid Json"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                openupgrade.update_module_names(
                    self.cr, {}.items(), environment_namespec=True
                )
        # Rename dummy module back into original name using namespec
        with mock.patch.dict(
            os.environ,
            {"OPENUPGRADE_RENAMED_MODULES": json.dumps({new: old})},
            clear=True,
        ):
            openupgrade.update_module_names(
                self.cr, {}.items(), environment_namespec=True
            )
        dummy_module = Mod.search([("name", "=", old)])
        renamed_module = Mod.search([("name", "=", new)])
        self.assertTrue(dummy_module)
        self.assertFalse(renamed_module)
        # Merge dummy module into base
        openupgrade.update_module_names(
            self.cr, {old: "base"}.items(), merge_modules=True
        )
        dummy_module = Mod.search([("name", "=", new)])
        renamed_module = Mod.search([("name", "=", old)])
        self.assertFalse(dummy_module)
        self.assertFalse(renamed_module)

    def _create_xml_id(self, record, name):
        self.env["ir.model.data"].create(
            {
                "module": "openupgradelib_tests",
                "name": name,
                "model": record._name,
                "res_id": record.id,
            }
        )
        return "openupgradelib_tests.%s" % name

    def test_delete_records_safely_by_xml_id(self):
        partner = self.env["res.partner"].create({"name": "Test partner"})
        child = self.env["res.partner"].create(
            {"name": "Test child partner", "parent_id": partner.id}
        )
        xml_id = self._create_xml_id(partner, "test_partner")
        openupgrade.delete_records_safely_by_xml_id(self.env, [xml_id])
        self.assertFalse(partner.exists())
        self.assertTrue(child.exists())
        self.assertFalse(self.env.ref(xml_id, raise_if_not_found=False))
        child.unlink()

    def test_delete_records_safely_by_xml_id_children(self):
        """The hierarchy is taken from the `_parent_name` model attribute, and
        the children are removed even if they don't have an XML-ID."""
        partner = self.env["res.partner"].create({"name": "Test partner"})
        child = self.env["res.partner"].create(
            {"name": "Test child partner", "parent_id": partner.id}
        )
        grandchild = self.env["res.partner"].create(
            {"name": "Test grandchild partner", "parent_id": child.id}
        )
        xml_id = self._create_xml_id(partner, "test_partner")
        grandchild_xml_id = self._create_xml_id(grandchild, "test_grandchild_partner")
        openupgrade.delete_records_safely_by_xml_id(
            self.env, [xml_id], delete_childs=True
        )
        self.assertFalse(partner.exists())
        self.assertFalse(child.exists())
        self.assertFalse(grandchild.exists())
        self.assertFalse(self.env.ref(grandchild_xml_id, raise_if_not_found=False))

    def test_delete_records_safely_by_xml_id_view_children(self):
        """Views are removed leaf first, as `inherit_id` is `ondelete=restrict`
        and its hierarchy is not declared in the model. The leaf first order
        has to be kept when records with and without an XML-ID are mixed."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "Test view",
                "model": "res.partner",
                "arch": """<form><field name="name"/></form>""",
            }
        )
        child_view = self.env["ir.ui.view"].create(
            {
                "name": "Test child view",
                "model": "res.partner",
                "inherit_id": view.id,
                "arch": """
                    <field name="name" position="after">
                        <field name="function"/>
                    </field>
                """,
            }
        )
        grandchild_view = self.env["ir.ui.view"].create(
            {
                "name": "Test grandchild view",
                "model": "res.partner",
                "inherit_id": child_view.id,
                "arch": """
                    <field name="function" position="after">
                        <field name="ref"/>
                    </field>
                """,
            }
        )
        xml_id = self._create_xml_id(view, "test_view")
        child_xml_id = self._create_xml_id(child_view, "test_child_view")
        openupgrade.delete_records_safely_by_xml_id(
            self.env, [xml_id], delete_childs=True
        )
        self.assertFalse(view.exists())
        self.assertFalse(child_view.exists())
        self.assertFalse(grandchild_view.exists())
        self.assertFalse(self.env.ref(child_xml_id, raise_if_not_found=False))

    def test_delete_records_safely_by_xml_id_parent_field_name(self):
        """The parent field can be passed explicitly, and archived children
        are removed as well."""
        partner = self.env["res.partner"].create({"name": "Test partner"})
        child = self.env["res.partner"].create(
            {"name": "Test child partner", "parent_id": partner.id, "active": False}
        )
        xml_id = self._create_xml_id(partner, "test_partner")
        openupgrade.delete_records_safely_by_xml_id(
            self.env, [xml_id], delete_childs=True, parent_field_name="parent_id"
        )
        self.assertFalse(partner.exists())
        self.assertFalse(child.exists())

    def test_delete_records_safely_by_xml_id_no_hierarchy(self):
        """Models without a hierarchy are removed without complaining."""
        group = self.env["res.country.group"].create({"name": "Test country group"})
        xml_id = self._create_xml_id(group, "test_country_group")
        with self.assertLogs("OpenUpgrade", level="ERROR") as log_catcher:
            openupgrade.delete_records_safely_by_xml_id(
                self.env, [xml_id], delete_childs=True
            )
        self.assertIn("has no parent field", log_catcher.output[0])
        self.assertFalse(group.exists())

    def tearDown(self):
        super().tearDown()
        self.cr.close()
