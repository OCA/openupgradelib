# -*- coding: utf-8 -*-
import os
import sys

from . import test_openupgradelib
# only run openupgrade tests with python 2.7 on travis
if sys.version_info[:2] == (2, 7):
    from . import test_openupgradelib_with_openupgrade
else:
    import unittest
    class test_openupgradelib_with_openupgrade(unittest.TestCase):
        pass
