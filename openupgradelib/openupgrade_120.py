# Copyright 2019 Tecnativa - Jairo Llopis
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Tools specific for migrating Odoo 11.0 to 12.0.

Important changes come from the update from Bootstrap 3 to 4.
To understand these changes, these sources have been consulted, among others
specific to some rules that can be consulted in inline comments:

* http://upgrade-bootstrap.bootply.com/
* https://bit.ly/2xmUHmo
* https://getbootstrap.com/docs/4.3/migration/#stable-changes
* https://github.com/odoo/odoo/wiki/Tips-and-tricks:-BS3-to-BS4

Don't expect perfection. But patches are welcome.
"""

from itertools import product
from psycopg2.extensions import AsIs

from .openupgrade import update_field_multilang
from .openupgrade_tools import (
    convert_html_fragment,
    convert_html_replacement_class_shortcut as _r,
)
import logging

logger = logging.getLogger('OpenUpgrade')
logger.setLevel(logging.DEBUG)

_COLS = range(1, 13)
_CONTEXTS = (
    # (BS3 context, BS4 context)
    ("default", "secondary"),
    ("primary", "primary"),
    ("active", "active"),
    ("disabled", "disabled"),
    ("success", "success"),
    ("info", "info"),
    ("warning", "warning"),
    ("danger", "danger"),
)
_TIERS = (
    # (BS3 tier, BS4 tier)
    ("-lg", "-xl"),
    ("-md", "-lg"),
    ("-sm", "-md"),
    ("-xs", ""),
)
_BS3_VISIBLES = ("block", "inline", "inline-block")

# These replacements are from standard Bootstrap 3 to 4
_BS4_REPLACEMENTS = (
    # Convert columns and modifiers among tiers
    *(_r("col%s-%s" % (t3, col), "col%s-%s" % (t4, col))
      for (t3, t4), col in product(_TIERS, _COLS)),
    *(_r("col%s-offset-%s" % (t3, col), "offset%s-%s" % (t4, col))
      for (t3, t4), col in product(_TIERS, _COLS)),
    *(_r("col%s-pull-%s" % (t3, col), "order-first")
      for (t3, t4), col in product(_TIERS, _COLS)),
    *(_r("col%s-push-%s" % (t3, col), "order-last")
      for (t3, t4), col in product(_TIERS, _COLS)),

    # Typography
    _r(selector="blockquote", class_add="blockquote"),
    _r(selector="blockquote > small", class_add="blockquote-footer"),
    _r("blockquote-reverse", "blockquote text-right"),
    _r(selector=".list-inline > li", class_add="list-linline-item"),

    # .page-header dropped. See https://stackoverflow.com/a/49708022/1468388
    _r("page-header", "pb-2 mt-4 mb-2 border-bottom"),

    # <dl> & co. See https://stackoverflow.com/a/56020841/1468388
    _r("dl-horizontal", "row"),
    _r(selector=".dl-horizontal > dt",
       class_add="col-sm-3 text-sm-right"),
    _r(selector=".dl-horizontal > dd", class_add="col-sm-9"),

    # Images
    _r("img-circle", "rounded-circle"),
    _r("img-responsive", "img-fluid d-block"),
    _r("img-rounded", "rounded"),

    # Tables
    _r("table-condensed", "table-sm"),
    *(_r("%s" % c3, "table-%s" % c4, selector=".table .%s" % c3)
      for (c3, c4) in _CONTEXTS),

    # Forms
    _r("control-label", "col-form-label"),
    _r("form-group-lg", "form-control-lg"),
    _r("form-group-sm", "form-control-sm"),
    _r("input-lg", "form-control-lg"),
    _r("input-sm", "form-control-sm"),
    _r("help-block", "form-text"),
    _r(selector="div.checkbox, div.radio",
       class_rm="checkbox radio", class_add="form-check"),
    _r(selector="div.form-check label", class_add="form-check-label"),
    _r(selector="div.form-check input", class_add="form-check-input"),
    _r(selector="label.checkbox-inline",
       class_rm="checkbox-inline",
       class_add="form-check-label form-check-inline"),
    _r(selector=".checkbox-inline input",
       class_rm="radio checkbox", class_add="form-check-input"),
    _r(selector=".form-horizontal .form-group", class_add="row"),
    _r(selector=".form-horizontal .form-group .control-label",
       class_rm="control-label", class_add="col-form-label text-right"),
    _r(selector=".form-horizontal", class_rm="form-horizontal"),
    _r("form-control-static", "form-control-plaintext"),

    # Input groups
    _r(selector=".form-control + .input-group-addon",
       class_rm="input-group-addon", class_add="input-group-text",
       wrap="<span class='input-group-append'/>"),
    _r(selector=".form-control + .input-group-btn",
       class_rm="input-group-btn", class_add="input-group-append"),
    _r("input-group-addon", "input-group-text",
       wrap="<span class='input-group-prepend'/>"),
    _r("input-group-btn", "input-group-prepend"),

    # Buttons
    _r("btn-default", "btn-secondary"),
    _r("btn-xs", "btn-sm"),
    _r("btn-group-xs", "btn-group-sm"),
    _r("btn-group-justified", "w-100",
       wrap='<div class="btn-group d-flex" role="group"/>'),
    _r(selector=".btn-group + .btn-group", class_add="ml-1"),

    # Dropdowns
    _r("divider", "dropdown-divider", selector=".dropdown-menu > .divider"),
    _r(selector=".dropdown-menu > li > a", class_add="dropdown-item"),

    # List groups
    _r("list-group-item", "list-group-item-action",
       selector="a.list-group-item"),

    # Navs
    _r(selector=".nav > li", class_add="nav-item"),
    _r(selector=".nav > li > a", class_add="nav-link"),
    _r("nav-stacked", "flex-column"),

    # Navbar
    _r(selector="navbar", class_add="navbar-expand-sm"),
    _r("navbar-default", "navbar-light"),
    _r("navbar-toggle", "navbar-toggler"),
    _r("navbar-form", "form-inline"),
    _r("navbar-fixed-top", "fixed-top"),
    _r("navbar-btn", "nav-item"),
    _r("navbar-right", "ml-auto"),

    # Pagination
    _r(selector=".pagination > li", class_add="page-item"),
    _r(selector=".pagination > li > a", class_add="page-link"),

    # Breadcrumbs
    _r(selector=".breadcrumb > li", class_add="breadcrumb-item"),

    # Labels and badges
    _r("label", "badge"),
    _r("badge-default", "badge-secondary"),
    *(_r("label-%s" % c3, "badge-%s" % c4) for (c3, c4) in _CONTEXTS),

    # Convert panels, thumbnails and wells to cards
    _r("panel", "card"),
    _r("panel-body", "card-body"),
    _r("panel-default"),
    _r("panel-group"),
    _r("panel-footer", "card-footer"),
    _r("panel-heading", "card-header"),
    _r("panel-title", "card-title"),
    *(_r("panel-%s" % c3, "bg-%s" % c4) for (c3, c4) in _CONTEXTS),
    _r("well", "card card-body"),
    _r("thumbnail", "card card-body"),

    # Progress
    *(_r("progress-bar-%s" % c3, "bg-%s" % c4) for (c3, c4) in _CONTEXTS),
    _r("active", "progress-bar-animated", selector=".progress-bar.active"),

    # Carousel
    _r("carousel-control left", "carousel-control-prev"),
    _r("carousel-control right", "carousel-control-next"),
    _r(selector=".item>.img", class_add="d-block"),
    _r("item", "carousel-item", selector=".carousel .item"),
    _r("left", "carousel-item-left", selector=".carousel .left"),
    _r("next", "carousel-item-next", selector=".carousel .next"),
    _r("prev", "carousel-item-prev", selector=".carousel .prev"),
    _r("right", "carousel-item-right", selector=".carousel .right"),

    # Utilities
    _r("center-block", "d-block mx-auto"),
    _r("hidden", "d-none"),
    _r("hidden-xs", "d-none d-md-block"),
    _r(selector=".hidden-sm",
       class_rm="hidden-sm d-md-block",
       class_add="d-md-none d-lg-block"),
    _r(selector=".hidden-md",
       class_rm="hidden-md d-lg-block",
       class_add="d-lg-none d-xl-block"),
    _r(selector=".hidden-lg",
       class_rm="hidden-lg d-xl-block",
       class_add="d-xl-none"),
    _r("hidden-lg", "d-xl-none"),
    *(_r("hidden%s" % t3, "d-none%s" % t4) for (t3, t4) in _TIERS),
    _r("hidden-print", "d-print-none"),
    *(_r("visible%s-%s" % (t3, vis), "d-")
      for (t3, t4), vis in product(_TIERS, _BS3_VISIBLES)),
    *(_r("visible-print-%s" % vis, "d-print-%s" % vis)
      for vis in _BS3_VISIBLES),
    _r("pull-left", "float-left"),
    _r("pull-right", "float-right"),
)

# These replacements are specific for Odoo v11 to v12
_ODOO12_REPLACEMENTS = (
    # Grays renamed; handpicked closest gray equivalent matches
    *(_r("bg-gray%s" % v11, "bg-%d00" % v12)
      for v11, v12 in (
          ("-darker", 9), ("-dark", 8), ("", 7),
          ("-light", 6), ("-lighter", 1))),

    # Odoo v12 editor adds/removes <b> tags, not <strong> tags; keep UX
    _r(selector="strong", tag="b"),

    # 25% opacity black background had white text in v11, but black in v12
    _r(selector=".bg-black-25", class_add="text-white"),

    # Image floating snippet disappears
    _r(selector=".o_image_floating.o_margin_s.float-left", class_add="mr8"),
    _r(selector=".o_image_floating.o_margin_s.float-right", class_add="ml8"),
    _r(selector=".o_image_floating.o_margin_m.float-left",
       style_add={"margin-right": "12px"}),
    _r(selector=".o_image_floating.o_margin_m.float-right",
       style_add={"margin-left": "12px"}),
    _r(selector=".o_image_floating.o_margin_l.float-left", class_add="mr16"),
    _r(selector=".o_image_floating.o_margin_l.float-right", class_add="ml16"),
    _r(selector=".o_image_floating.o_margin_xl.float-left", class_add="mr32"),
    _r(selector=".o_image_floating.o_margin_xl.float-right", class_add="ml32"),
    _r(selector=".o_image_floating.o_margin_s", class_add="mb4"),
    _r(selector=".o_image_floating.o_margin_m", class_add="mb8"),
    _r(selector=".o_image_floating.o_margin_l",
       style_add={"margin-bottom": "12px"}),
    _r(selector=".o_image_floating.o_margin_xl", class_add="mb24"),
    _r(selector=".o_image_floating .o_footer", class_rm="o_footer"),
    _r(class_rm="s_image_floating"),
    _r("o_image_floating o_margin_s o_margin_m o_margin_l o_margin_xl",
       "col-5 p-0", selector=".o_image_floating"),

    # Big message (v11) or Banner (v12) snippet
    _r(selector=".jumbotron h1, .jumbotron .h1",
       style_add={"font-size": "63px"}),
    _r(selector=".jumbotron p", class_add="lead"),

    # Big picture snippet
    _r(selector=".s_big_picture h2", class_add="mt24"),

    # Slider (v11) or Carousel (v12) snippet
    _r(selector=".carousel",
       class_rm="s_banner oe_custom_bg",
       class_add="s_carousel s_carousel_default",
       style_rm={"height"},
       style_add=lambda styles, **kw: {
           "min-height": styles.get("height", "400px")}),
    _r(selector=".carousel-control-prev .fa-chevron-left",
       class_rm="fa fa-chevron-left",
       class_add="carousel-control-prev-icon",
       tag="span"),
    _r(selector=".carousel-control-next .fa-chevron-right",
       class_rm="fa fa-chevron-right",
       class_add="carousel-control-next-icon",
       tag="span"),

    # Text snippet loses its built-in headers
    _r(selector=".s_text_block h2", class_add="mt24"),

    # Cover snippet
    _r(selector=".s_text_block_image_fw .container > .row > div",
       style_add={"padding": "30px"}),

    # Image gallery snippet
    _r(selector=".s_image_gallery .o_indicators_left",
       class_rm="fa fa-chevron-left",
       class_add="text-center pt-2",
       style_rm={"overflow", "padding", "border"}),
    _r(selector=".s_image_gallery .o_indicators_left > br",
       wrap='<i class="fa fa-chevron-left"/>'),
    _r(selector=".s_image_gallery .o_indicators_right",
       class_rm="fa fa-chevron-right",
       class_add="text-center pt-2",
       style_rm={"overflow", "padding", "border"}),
    _r(selector=".s_image_gallery .o_indicators_right > br",
       class_add="fa fa-chevron-right", tag="i"),

    # Comparisons snippet
    _r(selector=".s_comparisons > .container > .row > div",
       class_add="s_col_no_bgcolor",
       attr_add={"data-name": "Box"}),
    _r(selector=".s_comparisons .card .list-group",
       class_add="list-group-flush"),

    # Company team snippet
    _r(selector=".s_company_team h1", class_add="mt24"),

    # Call to action snippet
    _r(selector=".s_button .lead:first-child", class_rm="lead", tag="h3"),

    # Parallax sliders
    _r(selector=".s_parallax", style_add={"min-height": "200px"}),
    _r(selector=".s_parallax_slider .blockquote",
       style_add={"border-left": "5px solid #eeeeee"}),

    # Accordion snippet
    _r(selector=".s_faq_collapse .card-header h4", class_add="mb0"),
    _r(selector=".s_faq_collapse .panel", class_add="mt6"),

    # Well snippet
    _r(selector=".s_well.card", class_add="bg-100"),

    # Panel snippet
    _r("s_panel", "s_card"),
    _r(selector=".s_card.bg-secondary",
       class_rm="bg-secondary", class_add="bg-white"),
)

ALL_REPLACEMENTS = _BS4_REPLACEMENTS + _ODOO12_REPLACEMENTS


def convert_string_bootstrap_3to4(html_string, pretty_print=True):
    """Convert an HTML string from Bootstrap 3 to 4.

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
            html_string, ALL_REPLACEMENTS, pretty_print,
        )
    except Exception:
        logger.error(
            'Error converting string BS3 to BS4:\n%s' % html_string
        )
        raise


def convert_field_bootstrap_3to4(env, model_name, field_name, domain=None,
                                 method='orm'):
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
        return _convert_field_bootstrap_3to4_orm(
            env, model_name, field_name, domain,
        )
    records = env[model_name].search(domain or [])
    return _convert_field_bootstrap_3to4_sql(
        env.cr,
        records._table,
        field_name,
    )


def _convert_field_bootstrap_3to4_orm(env, model_name, field_name,
                                      domain=None):
    """Convert a field from Bootstrap 3 to 4, using Odoo ORM.

    :param odoo.api.Environment env: Environment to use.
    :param str model_name: Model to update.
    :param str field_name: Field to convert in that model.
    :param domain list: Domain to restrict conversion.
    """
    domain = domain or [
        (field_name, "!=", False), (field_name, "!=", "<p><br></p>")
    ]
    records = env[model_name].search(domain)
    update_field_multilang(
        records,
        field_name,
        lambda old, *a, **k: convert_string_bootstrap_3to4(old),
    )


def _convert_field_bootstrap_3to4_sql(cr, table, field, ids=None):
    """Convert a field from Bootstrap 3 to 4, using raw SQL queries.

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
        new_content = convert_string_bootstrap_3to4(old_content)
        if old_content != new_content:
            cr.execute(
                "UPDATE %s SET %s = %s WHERE id = %s",
                AsIs(table), AsIs(field), new_content, id_,
            )
