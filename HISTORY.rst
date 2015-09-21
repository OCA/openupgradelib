.. :changelog:

History
-------

0.1.0 (2015-05-04)
------------------

* First release on PyPI.

0.1.1 (2015-05-05)
------------------

* Fixes to the tests
* Add more badges
* Fix pip install issue with required.txt

0.1.2 (2015-06-23)
------------------

* Rewrite history with git filter-branch
* Remove unneeded files from history
  * openupgrade_loading.py
  * deferred80.py
  * openupgrade_log.py
  * #openupgrade_loading.py#

1.0.0 (2015-08-10)
------------------

* Rerelease to pypi with proper upload
* Include requirements.txt
* Mark as Beta

1.1.0 (2015-09-21)
------------------

* [IMP] set_defaults: Don't use ORM by default.
* Remove pip imports which break coverage with pypy3
* Add basic coverage configuration
* Factor out duplicated metadata about package
* [IMP] Google or NymPy docstrings
* [IMP] docstrings `copy_columns`, `rename_columns`
* [IMP] update_module_names: Handle ir_translation
* [FIX] lib for working with old API (<= 7.0)
* [FIX] set_defaults: Cope with inherited fields by delegation
