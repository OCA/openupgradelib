#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_openupgradelib
----------------------------------

Tests for `openupgradelib` module.
"""
import sys
import unittest
import mock

# Store original __import__
orig_import = __import__
# This will be the openerp module
openerp_mock = mock.Mock()
openerp_mock.release = mock.Mock()
openerp_mock.release.version_info = (8, 0, 0, 'final', 0)


def import_mock(name, *args):
    names = name.split('.')
    if names[0] in ['openerp', 'psycopg2']:
        return openerp_mock
    return orig_import(name, *args)

if sys.version_info[0] == 3:
    import builtins
    import_str = 'builtins.__import__'
else:
    import_str = '__builtin__.__import__'


def mock_contextmanager():
    fake_contextmanager = mock.Mock()
    fake_contextmanager.__enter__ = lambda self: None
    fake_contextmanager.__exit__ = lambda self, t, v, tb: None
    return fake_contextmanager


with mock.patch(import_str, side_effect=import_mock):
    from openupgradelib import openupgrade
    from openerp import api
    api.Environment.manage = mock_contextmanager


class TestOpenupgradelib(unittest.TestCase):

    def setUp(self):
        self.cr = mock.Mock()
        self.cr.savepoint = mock_contextmanager

    def test_migrate_env(self):
        @openupgrade.migrate()
        def migrate_with_cr(cr, version):
            self.assertTrue(isinstance(cr, mock.Mock))

        @openupgrade.migrate(use_env=True)
        def migrate_with_env(env, version):
            self.assertTrue(isinstance(env.cr, mock.Mock))

        migrate_with_cr(self.cr, 'irrelevant.version')
        migrate_with_env(self.cr, 'irrelevant.version')

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main()
