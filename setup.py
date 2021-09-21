#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import openupgradelib

from setuptools import setup


with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read().replace('.. :changelog:', '')

dirname = os.path.dirname(__file__)

test_requirements = [
    'coverage',
    'flake8',
    'pep8-naming',
    'mock',
]

setup(
    name='openupgradelib',
    use_scm_version=True,
    description=openupgradelib.__doc__,
    long_description=readme + '\n\n' + history,
    author=openupgradelib.__author__,
    author_email=openupgradelib.__email__,
    url='https://github.com/OCA/openupgradelib',
    packages=['openupgradelib'],
    include_package_data=True,
    setup_requires=["setuptools_scm"],
    install_requires=[
        "lxml",
        "cssselect",
        'importlib_metadata; python_version<"3.8"',
    ],
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    license=openupgradelib.__license__,
    zip_safe=False,
    keywords='openupgradelib',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
    ],
    test_suite='tests',
    tests_require=test_requirements
)
