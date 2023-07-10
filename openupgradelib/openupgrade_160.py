# Copyright 2022 ACSONE SA/NV
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""This module provides simple tools for OpenUpgrade migration, specific for
the >=16.0 migration.
"""
import itertools
import logging
from itertools import product

from psycopg2.extensions import AsIs

from odoo.tools.translate import _get_translation_upgrade_queries

from .openupgrade import logged_query, table_exists, update_field_multilang
from .openupgrade_tools import (
    convert_html_fragment,
    convert_html_replacement_class_shortcut as _r,
    replace_html_replacement_attr_shortcut as _attr_replace,
)

logger = logging.getLogger("OpenUpgrade")
logger.setLevel(logging.DEBUG)


def migrate_translations_to_jsonb(env, fields_spec):
    """
    In Odoo 16, translated fields no longer use the model ir.translation.
    Instead they store all their values into jsonb columns
    in the model's table.
    See https://github.com/odoo/odoo/pull/97692 for more details.

    Odoo provides a method _get_translation_upgrade_queries returning queries
    to execute to migrate all the translations of a particular field.

    The present openupgrade method executes the provided queries
    on table _ir_translation if exists (when ir_translation table was renamed
    by Odoo's migration scripts) or on table ir_translation (if module was
    migrated by OCA).

    This should be called in a post-migration script of the module
    that contains the definition of the translatable field.

    :param fields_spec: list of tuples of (model name, field name)
    """
    initial_translation_tables = None
    if table_exists(env.cr, "_ir_translation"):
        initial_translation_tables = "_ir_translation"
    elif table_exists(env.cr, "ir_translation"):
        initial_translation_tables = "ir_translation"
    if initial_translation_tables:
        for model, field_name in fields_spec:
            field = env[model]._fields[field_name]
            for query in itertools.chain.from_iterable(
                _get_translation_upgrade_queries(env.cr, field)
            ):
                if initial_translation_tables == "ir_translation":
                    query = query.replace("_ir_translation", "ir_translation")
                logged_query(env.cr, query)


_BADGE_CONTEXTS = (
    "secondary",
    "primary",
    "success",
    "info",
    "warning",
    "danger",
)

_RTL_REPLACEMENT_CONTEXT = (
    ("left", "start"),
    ("right", "end"),
)

_RTL_REPLACEMENT_ELEMENT = (
    "text",
    "float",
    "border",
    "border-top",
    "border-bottom",
    "rounded",
)

_MARGIN_PADDING_ELEMENT_REPLACEMENT = (
    ("pl", "ps"),
    ("ml", "ms"),
    ("pr", "pr"),
    ("mr", "me"),
)

_MARGIN_PADDING_SIZE = ("0", "1", "2", "3", "4", "5", "auto")

_MARGIN_PADDING = ("sm", "lg")

# These replacements are from standard Bootstrap 4 to 5
_BS5_REPLACEMENTS = (
    # Grid stuff
    _r(class_rm="no-gutters", class_add="g-0"),
    _r(class_rm="media", class_add="d-flex"),
    _r("media-body", "flex-grow-1"),
    # Content, Reboot, etc
    _r("thead-light", "table-light"),
    _r("thead-dark", "table-dark"),
    _r(
        "text-justify", "text-center"
    ),  # actually boostrap 5 only drop without any replacements
    # RTL
    *(
        _r("%s-%s" % (elem, t4), "%s-%s" % (elem, t5))
        for (t4, t5), elem in product(
            _RTL_REPLACEMENT_CONTEXT, _RTL_REPLACEMENT_ELEMENT
        )
    ),
    _r("pl", "ps"),
    _r("pr", "pe"),
    _r("ml", "ms"),
    _r("mr", "me"),
    # For stub like pl-0 -> ps-0
    *(
        _r("%s-%s" % (t4, size), "%s-%s" % (t5, size))
        for (t4, t5), size in product(
            _MARGIN_PADDING_ELEMENT_REPLACEMENT, _MARGIN_PADDING_SIZE
        )
    ),
    # For stub like ml-sm-1 -> ms-sm-1
    *(
        _r("%s-%s-%s" % (t4, context, size), "%s-%s-%s" % (t5, context, size))
        for (t4, t5), context, size in product(
            _MARGIN_PADDING_ELEMENT_REPLACEMENT, _MARGIN_PADDING, _MARGIN_PADDING_SIZE
        )
    ),
    # Forms
    _r("custom-control", "form-control"),
    _r("custom-checkbox", "form-check"),
    _r("custom-control-input", "form-check-input"),
    _r("custom-control-label", "form-check-label"),
    _r("custom-switch", "form-switch"),
    _r("custom-select", "form-select"),
    _r("custom-select-sm", "form-select-sm"),
    _r("custom-select-lg", "form-select-lg"),
    _r("custom-range", "form-range"),
    _r("form-control-file", "form-control"),
    _r("form-control-range", "form-control"),
    _r(selector="span.input-group-append", class_rm="input-group-append"),
    _r(
        selector="div.input-group-append",
        class_rm="input-group-append",
        class_add="input-group-text",
    ),
    _r(selector="div.input-group-prepend", class_rm="input-group-prepend"),
    _r(
        selector="span.input-group-prepend",
        class_rm="input-group-prepend",
    ),
    _r(class_rm="form-row", class_add="row"),
    _r(selector=".form-inline", class_rm="form-inline"),
    # Badges
    *(
        _r(class_rm="badge-%s" % badge_context, class_add="bg-%s" % badge_context)
        for badge_context in _BADGE_CONTEXTS
    ),
    _r(class_rm="badge-pill", class_add="rounded-pill"),
    # Close button
    _r(class_rm="close", class_add="btn-close"),
    # Utilities
    _r("text-monospace", "font-monospace"),
    _r("text-hide", "visually-hidden"),
    _r("font-weight-normal", "fw-normal"),
    _r("font-weight-bold", "fw-bold"),
    _r("font-weight-lighter", "fw-lighter"),
    _r("font-weight-bolder", "fw-bolder"),
    _r("font-weight-medium", "fw-medium"),
    _r("font-weight-normal", "fw-normal"),
    _r("font-weight-normal", "fw-normal"),
    _r("font-italic", "fst-italic"),
    _r("font-normal", "fst-normal"),
    _r("rounded-sm", "rounded-1"),
    _r("rounded-lg", "rounded-3"),
    # Helpers
    _r(selector="embed-responsive-item", class_rm="embed-responsive-item"),
    _r("sr-only", "visually-hidden"),
    _r("sr-only-focusable", "visually-hidden-focusable"),
    # JavaScript
    _attr_replace(
        selector="//*[@data-ride]",
        selector_mode="xpath",
        attr_rp={"data-ride": "data-bs-ride"},
    ),
    _attr_replace(
        selector="//*[@data-interval]",
        selector_mode="xpath",
        attr_rp={"data-interval": "data-bs-interval"},
    ),
    _attr_replace(
        selector="//*[@data-toggle]",
        selector_mode="xpath",
        attr_rp={"data-toggle": "data-bs-toggle"},
    ),
    _attr_replace(
        selector="//*[@data-dismiss]",
        selector_mode="xpath",
        attr_rp={"data-dismiss": "data-bs-dismiss"},
    ),
    _attr_replace(
        selector="//*[@data-trigger]",
        selector_mode="xpath",
        attr_rp={"data-trigger": "data-bs-trigger"},
    ),
    _attr_replace(
        selector="//*[@data-target]",
        selector_mode="xpath",
        attr_rp={"data-target": "data-bs-target"},
    ),
    _attr_replace(
        selector="//*[@data-spy]",
        selector_mode="xpath",
        attr_rp={"data-spy": "data-bs-spy"},
    ),
    _attr_replace(
        selector="//*[@data-display]",
        selector_mode="xpath",
        attr_rp={"data-display": "data-bs-display"},
    ),
    _attr_replace(
        selector="//*[@data-backdrop]",
        selector_mode="xpath",
        attr_rp={"data-backdrop": "data-bs-backdrop"},
    ),
    _attr_replace(
        selector="//*[@data-original-title]",
        selector_mode="xpath",
        attr_rp={"data-original-title": "data-bs-original-title"},
    ),
    _attr_replace(
        selector="//*[@data-template]",
        selector_mode="xpath",
        attr_rp={"data-template": "data-bs-template"},
    ),
    _attr_replace(
        selector="//*[@data-html]",
        selector_mode="xpath",
        attr_rp={"data-html": "data-bs-html"},
    ),
    _attr_replace(
        selector="//*[@data-slide]",
        selector_mode="xpath",
        attr_rp={"data-slide": "data-bs-slide"},
    ),
    _attr_replace(
        selector="//*[@data-slide-to]",
        selector_mode="xpath",
        attr_rp={"data-slide-to": "data-bs-slide-to"},
    ),
    _attr_replace(
        selector="//*[@data-parent]",
        selector_mode="xpath",
        attr_rp={"data-parent": "data-bs-parent"},
    ),
    _attr_replace(
        selector="//*[@data-focus]",
        selector_mode="xpath",
        attr_rp={"data-focus": "data-bs-focus"},
    ),
    _attr_replace(
        selector="//*[@data-content]",
        selector_mode="xpath",
        attr_rp={"data-content": "data-bs-content"},
    ),
    _attr_replace(
        selector="//*[@data-placement]",
        selector_mode="xpath",
        attr_rp={"data-placement": "data-bs-placement"},
    ),
)

# These replacements are specific for Odoo v15 to v16
_ODOO16_REPLACEMENTS = (
    # Form
    _r(class_rm="form-group", class_add="mb-3"),
    # Helpers
    _r(selector="embed-responsive-16by9", class_rm="embed-responsive"),
    _r("embed-responsive-16by9", "ratio ratio-16x9"),
    # Javascript
    _attr_replace(
        selector="//*[@data-keyboard]",
        selector_mode="xpath",
        attr_rp={"data-keyboard": "data-bs-keyboard"},
    ),
)

ALL_REPLACEMENTS = _BS5_REPLACEMENTS + _ODOO16_REPLACEMENTS


def convert_string_bootstrap_4to5(html_string, pretty_print=True):
    """Convert an HTML string from Bootstrap 4 to 5.

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
            ALL_REPLACEMENTS,
            pretty_print,
        )
    except Exception:
        logger.error("Error converting string BS4 to BS5:\n%s" % html_string)
        raise


def convert_field_bootstrap_4to5(
    env, model_name, field_name, domain=None, method="orm"
):
    """This converts all the values for the given model and field, being
    able to restrict to a domain of affected records.

    :param env: Odoo environment.
    :param model_name: Name of the model that contains the field.
    :param field_name: Name of the field that contains the BS3 HTML content.
    :param domain: Optional domain for filtering records in the model
    :param method: 'orm' (default) for using ORM; 'sql' for avoiding problems
        with extra triggers in ORM.
    """
    assert method in {"orm", "sql"}
    if method == "orm":
        return _convert_field_bootstrap_4to5_orm(
            env,
            model_name,
            field_name,
            domain,
        )
    records = env[model_name].search(domain or [])
    return _convert_field_bootstrap_4to5_sql(
        env.cr,
        records._table,
        field_name,
    )


def _convert_field_bootstrap_4to5_orm(env, model_name, field_name, domain=None):
    """Convert a field from Bootstrap 4 to 5, using Odoo ORM.

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
        lambda old, *a, **k: convert_string_bootstrap_4to5(old),
    )


def _convert_field_bootstrap_4to5_sql(cr, table, field, ids=None):
    """Convert a field from Bootstrap 4 to 5, using raw SQL queries.

    TODO Support multilang fields.

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
        new_content = convert_string_bootstrap_4to5(old_content)
        if old_content != new_content:
            cr.execute(
                "UPDATE %s SET %s = %s WHERE id = %s",
                AsIs(table),
                AsIs(field),
                new_content,
                id_,
            )
