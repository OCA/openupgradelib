# -*- coding: utf-8 -*-
import sys

__author__ = 'Odoo Community Association (OCA)'
__email__ = 'support@odoo-community.org'
__doc__ = """A library with support functions to be called from Odoo \
migration scripts."""
__license__ = "AGPL-3"


if sys.version_info >= (3, 8):
    from importlib.metadata import version, PackageNotFoundError
else:
    from importlib_metadata import version, PackageNotFoundError

try:
    __version__ = version("openupgradelib")
except PackageNotFoundError:
    # package is not installed
    pass
