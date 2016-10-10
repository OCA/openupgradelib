.. :changelog:

History
-------

1.2.0 (2016-10-10)
------------------

* [IMP] Lift constraints
* [IMP] Update module field in ir_model_fields when calling rename_models
* [ADD] allow to create an environment automatically
* [ADD] rename references to the model in mail related records
* [ADD] rename_property
* [IMP] clarifying docstring
* [FIX] doc typo
* [FIX] .travis.yml: remove Python 2.6 test
* [RFR] Move column_exists so it can be used during loading
* [MIG] 10.0 imports

1.1.2 (2016-06-13)
------------------

* [FIX] missing %% in convert_field_to_html()
* [FIX] Remove wrong docs
* [FIX] Avoid broken updates
* [IMP] Add new context manager allow_pgcodes
* [FIX] support OpenERP version that don't have cr.savepoint


1.1.1 (2015-10-30)
------------------

* [IMP] New function 'is_module_installed()'
* [ADD] when renaming a model, also move link in ir_attachment
* [FIX] Compatibility for OpenERP versions prior to 6.1
* [FIX] use correct column name in rename_models
* [IMP] .travis.yml: Add auto-deployment
* [IMP] map_values: Support set & notset selectors

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

1.0.0 (2015-08-10)
------------------

* Rerelease to pypi with proper upload
* Include requirements.txt
* Mark as Beta

0.1.2 (2015-06-23)
------------------

* Rewrite history with git filter-branch
* Remove unneeded files from history
  * openupgrade_loading.py
  * deferred80.py
  * openupgrade_log.py
  * #openupgrade_loading.py#

0.1.1 (2015-05-05)
------------------

* Fixes to the tests
* Add more badges
* Fix pip install issue with required.txt

0.1.0 (2015-05-04)
------------------

* First release on PyPI.
