# Copyright 2026 Hunki Enterprises BV
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import importlib
import re
from pathlib import Path

import lxml

from odoo.cli import upgrade_code
from odoo.tools.sql import SQL

from .openupgrade import logger

spec = importlib.util.spec_from_file_location(
    "odoo_icon_upgrade_code",
    Path(upgrade_code.ROOT) / "upgrade_code" / "19.5-00-material-symbols-icons.py",
)
odoo_icon_upgrade_code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(odoo_icon_upgrade_code)


def migrate_qweb_fields(env, model_name, *field_names):
    """
    Migrate QWEB code in env[model_name].field_name for all field name in field_names:

    - change t-esc to t-out in attributes and inherited views
    - replace fontawesome classes with their material counterpart

    Call this function in an end-migration script to avoid unneccesary updates of
    records that are overwritten anyways during the migration
    """
    Model = env[model_name]
    fields = Model._fields
    columns = []
    conditions = []
    for field_name in field_names:
        columns.append(SQL.identifier(field_name))
        name = (
            SQL.identifier(field_name)
            if not fields[field_name].translate
            and not fields[field_name].company_dependent
            else SQL("%s::text", SQL.identifier(field_name))
        )
        conditions.append(SQL("%s LIKE '%%t-esc%%'", name))
        conditions.append(SQL("%s LIKE '%%fa-%%'", name))

    migrate_view_inheritance = False
    if model_name == "ir.ui.view":
        columns.append(SQL.identifier("inherit_id"))
        migrate_view_inheritance = True

    def migrate_scalar(field_name, val, migrate_view_inheritance):
        if new_val := migrate_qweb_string(val, migrate_view_inheritance):
            return SQL("%s=%s", SQL.identifier(field_name), new_val)

    def migrate_json(field_name, val, migrate_view_inheritance):
        new_val = {}
        for key, value in val.items():
            if new_value := migrate_qweb_string(value, migrate_view_inheritance):
                new_val[key] = new_value
        if new_val:
            code, params = "%s", [SQL.identifier(field_name)]
            for key, value in new_val.items():
                code = f"jsonb_set({code}, ARRAY [%s], json_scalar(%s)::jsonb)"
                params.extend([key, value])
            return SQL(f"%s={code}", *([SQL.identifier(field_name)] + params))

    migration_funcs = {
        field_name: migrate_scalar
        if not fields[field_name].company_dependent and not fields[field_name].translate
        else migrate_json
        for field_name in field_names
    }

    env.cr.execute(
        SQL(
            f"SELECT id, %s FROM {Model._table} WHERE %s",
            SQL(", ").join(columns),
            SQL(" OR ").join(conditions),
        )
    )
    if env.cr.rowcount:
        logger.info(
            "Migrating %s.%s for %d records",
            model_name,
            ",".join(field_names),
            env.cr.rowcount,
        )
    for record in env.cr.dictfetchall():
        updates = []
        for field_name in field_names:
            if update := migration_funcs[field_name](
                field_name,
                record[field_name],
                migrate_view_inheritance and bool(record["inherit_id"]),
            ):
                updates.append(update)
        if updates:
            env.cr.execute(
                SQL(
                    f"UPDATE {Model._table} SET %s WHERE id={record['id']}",
                    SQL(", ").join(updates),
                )
            )


RE_T_ESC_XPATH = re.compile(r"\bt-esc\b")


def migrate_qweb_string(qweb_string, migrate_view_inheritance=False):
    """
    Migrate qweb code in qweb_string to v20.
    Return None if nothing has been changed.
    """
    changed = False
    root_node_added = False
    try:
        tree = lxml.etree.fromstring(qweb_string)
    except lxml.etree.XMLSyntaxError:
        tree = lxml.etree.fromstring(f"<root>{qweb_string}</root>")
        root_node_added = True
    for element in tree.iter():
        if t_esc := element.get("t-esc"):
            element.set("t-out", element.get("t-out") or t_esc)
            del element.attrib["t-esc"]
            changed = True
        if css_class := element.get("class"):
            class_to_icon = odoo_icon_upgrade_code._class_to_icon(css_class)
            if class_to_icon:
                element.set("class", class_to_icon[0])
                element.set("data-icon", class_to_icon[1])
                changed = True
        # TODO: do the class transition for t-att*, in view interitance, ... ?
        if migrate_view_inheritance:
            if element.tag == "xpath":
                expr = element.get("expr", "")
                if "t-esc" in expr:
                    new_expr = RE_T_ESC_XPATH.sub("t-out", expr)
                    if new_expr != expr:
                        element.set("expr", new_expr)
                        changed = True
            elif element.tag == "attribute" and element.get("name") == "t-esc":
                element.set("name", "t-out")
                changed = True
    return (
        changed
        and lxml.etree.tostring(tree, encoding="utf8")[
            root_node_added and 6 or 0 : root_node_added and -7 or None
        ].decode("utf8")
        or None
    )
