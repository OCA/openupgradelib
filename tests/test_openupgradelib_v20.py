# Copyright 2026 Hunki Enterprises BV
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import unittest

from . import common

# set in setUp
openupgrade_200 = None


class TestOpenupgradelibV20(common.TestOpenupgradelibCommon):
    def setUp(self):
        super().setUp()
        if common.openupgrade.version_info[0] != 20:
            raise unittest.SkipTest("Skipping v20-specific tests")
        global openupgrade_200
        openupgradelib = __import__("openupgradelib", fromlist=["openupgrade_200"])
        openupgrade_200 = openupgradelib.openupgrade_200

    def test_migrate_qweb_fields(self):
        """
        Test that qweb fields are converted correctly
        """
        view = self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "arch_db": """<div><span t-esc="object.value1"/>EN</div>""",
            }
        )
        view.update_field_translations("arch_db", {"fr_FR": {"EN": "FR"}})
        inherited_view = self.env["ir.ui.view"].create(
            {
                "type": "qweb",
                "inherit_id": view.id,
                "arch_db": """
                <data>
                <xpath expr="//span[@t-esc]" position="after">
                    <span t-out="object.value3" t-esc="object.value4" />
                    <span>Don't use t-esc any more</span>
                </xpath>
                <xpath expr="//span[@t-esc='object.value1']" position="attributes">
                    <attribute name="t-esc">object.value2</attribute>
                </xpath>
                </data>
            """,
            }
        )
        openupgrade_200.migrate_qweb_fields(
            self.env, "ir.ui.view", "arch_db", "arch_prev"
        )
        view.invalidate_model()
        self.assertEqual(view.arch_db, """<div><span t-out="object.value1"/>EN</div>""")
        self.assertEqual(
            view.with_context(lang="fr_FR").arch_db,
            """<div><span t-out="object.value1"/>FR</div>""",
        )
        self.assertEqual(
            view.arch_prev, """<div><span t-out="object.value1"/>EN</div>"""
        )
        self.assertEqual(
            inherited_view.arch_db,
            """<data>
                <xpath expr="//span[@t-out]" position="after">
                    <span t-out="object.value3"/>
                    <span>Don't use t-esc any more</span>
                </xpath>
                <xpath expr="//span[@t-out='object.value1']" position="attributes">
                    <attribute name="t-out">object.value2</attribute>
                </xpath>
                </data>""",
        )

    def test_migrate_qweb_string(self):
        """
        Test that migrate_qweb_string handles fragments correctly
        """
        self.assertFalse(
            openupgrade_200.migrate_qweb_string("don't use <b>t-esc</b> any more!")
        )
        self.assertEqual(
            openupgrade_200.migrate_qweb_string(
                '<div class="fa other-class fa-folder"/>'
            ),
            '<div class="oi oi-filled other-class" data-icon="folder"/>',
        )
