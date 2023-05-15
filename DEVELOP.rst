To contribute to the openupgradelib documentation:

- Clone locally the current branch and create a dedicated branch

.. code:: shell

    git clone https://github.com/OCA/openupgradelib -b documentation
    git checkout -b documentation-NEW-FEATURE

- Install required components in a virtualenv:

.. code:: shell

    git clone https://github.com/odoo/odoo -b 16.0 --depth=1 ./src/odoo
    virtualenv env --python=python3.10
    ./env/bin/pip install -e ./src/odoo/
    ./env/bin/pip install -e .
    ./env/bin/pip install -r ./doc_requirements.txt


- Make changes in the docsource folder

- Compile locally:

.. code:: shell

    . ./env/bin/activate
    python3 -m sphinx -d ./docs/.doctrees ./docsource ./docs
