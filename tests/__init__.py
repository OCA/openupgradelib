# -*- coding: utf-8 -*-
from sys import version_info
from . import test_openupgradelib
# only run openupgrade tests with python 2.7
if version_info[0] < 3:
    from . import test_openupgradelib_with_openupgrade
else:
    import unittest
    class test_openupgradelib_with_openupgrade(unittest.TestCase):
        pass
