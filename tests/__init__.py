# -*- coding: utf-8 -*-
import os
from . import test_openupgradelib
# only run openupgrade tests with python 2.7 on travis
# weirdly, the variable TRAVIS_PYTHON_VERSION also has the value of
# 2.7 for pypy at this point, so we cannot simply use this variable
if 'openupgradelib' in os.environ.get('PYTHONPATH', ''):
    from . import test_openupgradelib_with_openupgrade
else:
    import unittest
    class test_openupgradelib_with_openupgrade(unittest.TestCase):
        pass
