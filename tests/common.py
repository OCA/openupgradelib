import os
import unittest

import odoo

# needs to be imported after Odoo initialized, done in test setup
openupgradelib = None
openupgrade = None


class TestOpenupgradelibCommon(unittest.TestCase):
    """
    Test openupgradelib
    """

    def setUp(self):
        global openupgrade, openupgradelib
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
        openupgradelib = __import__(
            "openupgradelib", fromlist=["openupgrade", "openupgrade_merge_records"]
        )
        openupgrade = openupgradelib.openupgrade
