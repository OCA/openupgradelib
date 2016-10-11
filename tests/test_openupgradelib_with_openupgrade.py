#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import StringIO
import subprocess
import tempfile
import unittest
import urllib2
import tarfile

class TestOpenupgradelibWithOpenUpgrade(unittest.TestCase):

    def setUp(self):
        pass

    def _get_openupgrade(self, version):
        """download current openupgrade to some temp dir, return the dir
        containing the actual code"""
        tempdir = tempfile.mkdtemp()
        archive = tarfile.open(
            fileobj=StringIO.StringIO(urllib2.urlopen(
                'https://github.com/OCA/OpenUpgrade/archive/%s.tar.gz' %
                version
            ).read())
        )
        # github tar files contain the code in a folder named after the release
        folder_name = archive.next().name
        archive.extractall(path=tempdir)
        return os.path.join(tempdir, folder_name)

    def _test_openupgrade_generic(self, version):
        """run openupgrade in a new interpreter to see if all imports work"""
        # don't do anything if we're on the wrong python version
        if 'openupgradelib' not in os.environ.get('PYTHONPATH', ''):
            return
        ou_dir = self._get_openupgrade(version)
        try:
            subprocess.check_output([
                os.path.join(ou_dir, 'openerp-server'),
                '--help',
            ])
            self.assertTrue(True)
        except subprocess.CalledProcessError:
            self.assertTrue(False)

    def test_openupgrade_61(self):
        self._test_openupgrade_generic('6.1')

    def test_openupgrade_70(self):
        self._test_openupgrade_generic('7.0')

    def test_openupgrade_80(self):
        self._test_openupgrade_generic('8.0')

    def test_openupgrade_90(self):
        self._test_openupgrade_generic('9.0')

if __name__ == '__main__':
    unittest.main()
