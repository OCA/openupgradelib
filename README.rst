.. image:: https://img.shields.io/travis/OCA/openupgradelib.svg
    :target: https://travis-ci.org/OCA/openupgradelib
    :alt: Build Status

.. image:: https://coveralls.io/repos/OCA/openupgradelib/badge.svg?service=github
  :target: https://coveralls.io/github/OCA/openupgradelib
  :alt: Coverage Status

.. image:: https://codeclimate.com/github/OCA/openupgradelib/badges/gpa.svg
   :target: https://codeclimate.com/github/OCA/openupgradelib
   :alt: Code Climate

.. image:: https://img.shields.io/pypi/v/openupgradelib.svg
   :target: https://pypi.python.org/pypi/openupgradelib
   :alt: Pypi Package
   
.. image:: https://img.shields.io/badge/license-AGPL--3-blue.png
   :target: https://www.gnu.org/licenses/agpl-3.0
   :alt: License: AGPL-3

===============================
OpenUpgrade Library
===============================

A library with support functions to be called from Odoo migration scripts.
For information on how to develop and contribute

* Contributor Documentation: https://openupgradelib.readthedocs.org.

Install
-------

Always get the latest version through either pip or pip3:

``pip install --ignore-installed git+https://github.com/OCA/openupgradelib.git@master``

Features
--------

The OpenUpgrade library contains all kinds of helper functions for wrting scripts to migrate between odoo versions, in OpenUpgrade itself or in the migration scripts of your own module (in either major or minor version upgrades). Once installed, it can be used in your scripts as

``from openupgradelib import openupgrade``

* Library Documentation: https://oca.github.io/OpenUpgrade/API.html
