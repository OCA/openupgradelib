# Copyright 2023 Tecnativa - Pilar Vargas
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""This module provides simple tools for OpenUpgrade migration, specific for
the 13.0 -> 14.0 migration.
"""

import logging
from itertools import product

from psycopg2.extensions import AsIs

from .openupgrade import update_field_multilang
from .openupgrade_tools import (
    convert_html_fragment,
    convert_html_replacement_class_shortcut as _r,
)

logger = logging.getLogger("OpenUpgrade")
logger.setLevel(logging.DEBUG)

_PREFIX = ["bg-", "text-", "border-"]
_CONTEXTS = (
    ("alpha", 1),
    ("beta", 2),
    ("gamma", 3),
    ("delta", 4),
    ("epsilon", 5),
    ("zeta", 6),
    ("eta", 7),
)

# These replacements are specific for Odoo v13 to v14
_ODOO14_REPLACEMENTS = (
    *(
        _r(f"{prefix}{v13}", f"{prefix}o-color-{v14}")
        for prefix, (v13, v14) in product(_PREFIX, _CONTEXTS)
    ),
    *(_r(f"btn-{v13}", f"bg-o-color-{v14}") for (v13, v14) in _CONTEXTS),
    *(_r(f"btn-outline-{v13}", f"border-o-color-{v14}") for (v13, v14) in _CONTEXTS),
    _r("alert-gamma", "alert-info"),
)


def convert_html_string_13to14(html_string, pretty_print=True):
    """Convert an HTML string from odoo version 13 to 14.

    :param str html_string:
        Raw HTML fragment to convert.

    :param bool pretty_print:
        Indicate if you wish to return the HTML pretty formatted.

    :return str:
        Raw HTML fragment converted.
    """
    if not html_string:
        return html_string
    try:
        return convert_html_fragment(
            html_string,
            _ODOO14_REPLACEMENTS,
            pretty_print,
        )
    except Exception:
        logger.error("Error converting string:\n%s" % html_string)
        raise


def convert_field_html_string_13to14(
    env, model_name, field_name, domain=None, method="orm"
):
    """This converts all the values for the given model and field, being
    able to restrict to a domain of affected records.
    :param env: Odoo environment.
    :param model_name: Name of the model that contains the field.
    :param field_name: Name of the field that contains the HTML content.
    :param domain: Optional domain for filtering records in the model
    :param method: 'orm' (default) for using ORM; 'sql' for avoiding problems
        with extra triggers in ORM.
    """
    assert method in {"orm", "sql"}
    if method == "orm":
        return _convert_field_html_string_13to14_orm(
            env,
            model_name,
            field_name,
            domain,
        )
    return _convert_field_html_string_13to14_sql(
        env.cr,
        env[model_name]._table,
        field_name,
    )


def _convert_field_html_string_13to14_orm(env, model_name, field_name, domain=None):
    """Convert an html field from odoo version 13 to 14, using Odoo ORM.
    :param odoo.api.Environment env: Environment to use.
    :param str model_name: Model to update.
    :param str field_name: Field to convert in that model.
    :param domain list: Domain to restrict conversion.
    """
    domain = domain or [(field_name, "!=", False), (field_name, "!=", "<p><br></p>")]
    records = env[model_name].search(domain)
    update_field_multilang(
        records,
        field_name,
        lambda old, *a, **k: convert_html_string_13to14(old),
    )


def _convert_field_html_string_13to14_sql(cr, table, field, ids=None):
    """Convert an html field from odoo version 13 to 14, using raw SQL queries.
    :param odoo.sql_db.Cursor cr:
        Database cursor.
    :param str table:
        Table name.
    :param str field:
        Field name, which should contain HTML content.
    :param list ids:
        List of IDs, to restrict operation to them.
    """
    sql = "SELECT id, %s FROM %s " % (field, table)
    params = ()
    if ids:
        sql += "WHERE id IN %s"
        params = (ids,)
    cr.execute(sql, params)
    for id_, old_content in cr.fetchall():
        new_content = convert_html_string_13to14(old_content)
        if old_content != new_content:
            cr.execute(
                "UPDATE %s SET %s = %s WHERE id = %s",
                AsIs(table),
                AsIs(field),
                new_content,
                id_,
            )
