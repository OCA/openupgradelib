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

0.1.3 (2015-08-11)
------------------

* Add method decorator log to automatically log a line when the method is
  called
* Add method logged_progress for showing a progress bar to know the advance
  of that part of the migration
