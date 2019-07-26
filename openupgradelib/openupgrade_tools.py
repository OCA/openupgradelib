# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    This module copyright (C) 2012-2014 Therp BV (<http://therp.nl>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

# A collection of functions split off from openupgrade.py
# with no or only minimal dependencies
import logging

from lxml.etree import tostring
from lxml.html import fromstring


def table_exists(cr, table):
    """ Check whether a certain table or view exists """
    cr.execute('SELECT 1 FROM pg_class WHERE relname = %s', (table,))
    return cr.fetchone()


def column_exists(cr, table, column):
    """ Check whether a certain column exists """
    cr.execute(
        'SELECT count(attname) FROM pg_attribute '
        'WHERE attrelid = '
        '( SELECT oid FROM pg_class WHERE relname = %s ) '
        'AND attname = %s',
        (table, column))
    return cr.fetchone()[0] == 1


def convert_html_fragment(html_string, replacements, pretty_print=True):
    """Get a string that contains XML and apply replacements to it.

    :param str xml_string:
        XML string object.

    :param iterable[*dict] replacements:
        The spec is any iterable full of dicts with this format:

        .. code-block:: python

            {
                # This key is required, to find matching nodes
                "selector": ".carousel .item",

                # This is the default. Use ``xpath`` to select with XPath
                "selector_mode": "css",

                # Other keys are kwargs for ``convert_xml_node()``.
                "class_rm": "item",
                "class_add": "carousel-item",
            },

    :param bool pretty_print:
        Indicates if the returned XML string should be indented.

    :return str:
        Converted XML string.
    """
    try:
        fragment = fromstring(html_string)
    except Exception:
        logging.error("Failure converting string to DOM:\n%s", html_string)
        raise
    for spec in replacements:
        instructions = spec.copy()
        # Find matching nodes
        selector = instructions.pop("selector")
        mode = instructions.pop("selector_mode", "css")
        assert mode in {"css", "xpath"}
        finder = fragment.cssselect if mode == "css" else fragment.xpath
        nodes = finder(selector)
        # Apply node conversions as instructed
        for node in nodes:
            convert_xml_node(node, **instructions)
    # Return new XML string
    return tostring(fragment, pretty_print=pretty_print, encoding="unicode")


def convert_xml_node(node,
                     attr_add=None,
                     attr_rm=frozenset(),
                     class_add="",
                     class_rm="",
                     style_add=None,
                     style_rm=frozenset(),
                     tag="",
                     wrap=""):
    """Apply conversions to an XML node.

    All parameters except :param:`node` can be a callable that return the
    expected type as specified in each of them below.

    The callable would be called with these **keyword-only** arguments:

    * ``attrs``: A ``dict`` of the original attributes in the node.
    * ``classes``: A ``set`` of the original classes in the node.
    * ``styles``: A ``dict`` of the original styles in the node.
    * ``tag``: A ``str`` indicating the original node tag.

    Each one of them has the same type as the expected type

    :param lxml.etree.Element node:
        Node to be modified.

    :param dict attr_add:
        Attributes to add.

        If the attribute is present, it won't be overwritten unless you add
        it also to :param:`attr_rm`.

    :param set attr_rm:
        Attributes to remove.

    :param str class_add:
        Space-separated list of classes to add (for HTML nodes).

    :param str class_rm:
        Space-separated list of classes to remove (for HTML nodes).

    :param dict style_add:
        CSS styles to be added inline to the node (for HTML nodes). I.e.,
        if you pass ``{"display": "none"}``,
        a ``<div style="background-color:gray/>`` node would become
        ``<div style="background-color:gray;display:none/>``.

        If the style is present, it won't be overwritten unless you add
        it also to :param:`style_rm`.

    :param set style_rm:
        CSS styles to remove from the node (for HTML nodes). I.e.,
        if you pass ``{"display"}``,
        a ``<div style="background-color:gray;display:none/>`` node
        would become ``<div style="background-color:gray/>``.

    :param str tag:
        Use it to alter the element tag.

    :param str wrap:
        XML element that will wrap the :param:`node`.
    """
    # Fix params
    attr_add = attr_add or {}
    class_add = set(class_add.split())
    class_rm = set(class_rm.split())
    style_add = style_add or {}
    # Obtain attributes, classes and styles
    classes = set(node.attrib.get("class", "").split())
    styles = node.attrib.get("style", "").split(";")
    styles = {key.strip(): val.strip() for key, val in
              (style.split(":", 1) for style in styles if ":" in style)}
    # Convert incoming callable arguments into values
    originals = {
        "attrs": dict(node.attrib.items()),
        "classes": classes.copy(),
        "styles": styles.copy(),
        "tag": node.tag,
    }
    _call = lambda v: v(**originals) if callable(v) else v  # noqa: E731
    attr_add = _call(attr_add)
    attr_rm = _call(attr_rm)
    class_add = _call(class_add)
    class_rm = _call(class_rm)
    style_add = _call(style_add)
    style_rm = _call(style_rm)
    tag = _call(tag)
    wrap = _call(wrap)
    # Patch node attributes
    if attr_add or attr_rm:
        for key in attr_rm:
            node.attrib.pop(key, None)
        for key, value in attr_add.items():
            if key not in node.attrib:
                node.attrib[key] = value
    # Patch node classes
    if class_add or class_rm:
        classes = (classes | class_add) ^ class_rm
        classes = " ".join(classes)
        if classes:
            node.attrib["class"] = classes
        else:
            node.attrib.pop("class", None)
    # Patch node styles
    if style_add or style_rm:
        for key in style_rm:
            styles.pop(key, None)
        for key, value in style_add.items():
            styles.setdefault(key, value)
        styles = ";".join(map(":".join, styles.items()))
        if styles:
            node.attrib["style"] = styles
        else:
            node.attrib.pop("style", None)
    # Change its tag if needed
    if tag:
        node.tag = tag
    # Wrap it if needed; see https://stackoverflow.com/a/56037842/1468388
    if wrap:
        wrapper = fromstring(wrap)
        node.getparent().replace(node, wrapper)
        wrapper.append(node)


def convert_html_replacement_class_shortcut(class_rm="", class_add="",
                                            **kwargs):
    """Shortcut to create a class replacement spec.

    :param str class_rm:
        Space-separated string with classes to remove. If a selector kwarg
        is not provided, these will be transformed to a selector, effectively
        generating a class replacement result. For example, if this parameter
        is ``"label badge"``, the default selector will be ``".label.badge"``.

    :param str class_add:
        Space-separated string with classes to add.

    :return dict:
        Generated spec, to be included in a list of replacements to be
        passed to :meth:`convert_xml_fragment`.
    """
    kwargs.setdefault("selector", ".%s" % ".".join(class_rm.split()))
    assert kwargs["selector"] != "."
    kwargs.update({
        "class_rm": class_rm,
        "class_add": class_add,
    })
    return kwargs
