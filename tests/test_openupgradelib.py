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
    if name == 'openerp' or name.startswith("openerp."):
        return openerp_mock
    return orig_import(name, *args)

if sys.version_info[0] == 3:
    import builtins
    import_str = 'builtins.__import__'
else:
    import_str = '__builtin__.__import__'

with mock.patch(import_str, side_effect=import_mock):
    from openupgradelib import openupgrade


class TestOpenupgradelib(unittest.TestCase):

    def setUp(self):
        pass

    def test_something(self):
        pass

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main()
