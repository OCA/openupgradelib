# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

"""Tools specific for migrating from Odoo 12.0 to 13.0."""

import logging
from . import openupgrade

_logger = logging.getLogger('OpenUpgrade')


def convert_old_style_tax_tag_to_new(
        env, report_line, old_tag_id, new_debit_tag_id, new_credit_tag_id):
    _logger.debug("Converting %s to +/- %s..." % (report_line.name,
                                                  report_line.tag_name))

    # First, update the tax repartition lines' tags
    affected = openupgrade.logged_query(env.cr, """
        UPDATE account_account_tag_account_tax_repartition_line_rel r
        SET account_account_tag_id = %s
        FROM account_tax_repartition_line atrl
        WHERE
            r.account_tax_repartition_line_id = atrl.id AND
            atrl.invoice_tax_id IS NOT NULL AND
            atrl.refund_tax_id IS NULL AND
            r.account_account_tag_id = %s
    """ % (new_debit_tag_id, old_tag_id))
    if affected > 0:
        _logger.info('Converted tag "%s" to "+%s" on repartition line.' % (
            report_line.name,
            report_line.tag_name
        ))
    affected = openupgrade.logged_query(env.cr, """
        UPDATE account_tax_repartition_financial_tags r
        SET account_account_tag_id = %s
        FROM account_tax_repartition_line atrl
        WHERE
            r.account_tax_repartition_line_template_id = atrl.id AND
            atrl.invoice_tax_id IS NOT NULL AND
            atrl.refund_tax_id IS NULL AND
            r.account_account_tag_id = %s
    """ % (new_debit_tag_id, old_tag_id))
    if affected > 0:
        _logger.info('Converted tag "%s" to "+%s" on repartition line '
                     'template.' % (report_line.name, report_line.tag_name))
    affected = openupgrade.logged_query(env.cr, """
        UPDATE account_account_tag_account_tax_repartition_line_rel r
        SET account_account_tag_id = %s
        FROM account_tax_repartition_line atrl
        WHERE
            r.account_tax_repartition_line_id = atrl.id AND
            atrl.invoice_tax_id IS NULL AND
            atrl.refund_tax_id IS NOT NULL AND
            r.account_account_tag_id = %s
    """ % (new_credit_tag_id, old_tag_id))
    if affected > 0:
        _logger.info('Converted tag "%s" to "-%s" on repartition line.' % (
            report_line.name,
            report_line.tag_name
        ))
    affected = openupgrade.logged_query(env.cr, """
        UPDATE account_tax_repartition_financial_tags r
        SET account_account_tag_id = %s
        FROM account_tax_repartition_line atrl
        WHERE
            r.account_tax_repartition_line_template_id = atrl.id AND
            atrl.invoice_tax_id IS NULL AND
            atrl.refund_tax_id IS NOT NULL AND
            r.account_account_tag_id = %s
    """ % (new_credit_tag_id, old_tag_id))
    if affected > 0:
        _logger.info('Converted tag "%s" to "-%s" on repartition line '
                     'template.' % (report_line.name, report_line.tag_name))

    # Then, update the move line tags
    openupgrade.logged_query(env.cr, """
        UPDATE account_account_tag_account_move_line_rel r
        SET account_account_tag_id = %s
        FROM account_move_line aml
        WHERE
            r.account_move_line_id = aml.id AND
            aml.debit >= 0 AND
            r.account_account_tag_id = %s
    """, (new_debit_tag_id, old_tag_id))
    openupgrade.logged_query(env.cr, """
        UPDATE account_account_tag_account_move_line_rel r
        SET account_account_tag_id = %s
        FROM account_move_line aml
        WHERE
            r.account_move_line_id = aml.id AND
            aml.credit > 0 AND
            r.account_account_tag_id = %s
    """, (new_credit_tag_id, old_tag_id))

    # The old tag should be deleted or deactivated, because the l10n VAT
    # report would otherwise still use them. Besides, they are not
    # necessary anymore anyway.
    openupgrade.logged_query(env.cr, """
        UPDATE account_account_tag
        SET active = FALSE
        WHERE id = %s
    """, (old_tag_id,))


def unlink_invalid_tax_tags_from_move_lines(
        env, module, base_tag_xmlids, tax_tag_xmlids):
    openupgrade.logged_query(env.cr, """
        DELETE FROM account_account_tag_account_move_line_rel r
        WHERE
            account_account_tag_id IN (
                SELECT res_id FROM ir_model_data
                WHERE
                    model = 'account.account.tag' AND
                    module = %s AND
                    name IN ('""" + "','".join(tax_tag_xmlids) + """')
            ) AND
            account_move_line_id IN (
                SELECT id FROM account_move_line
                WHERE tax_base_amount = 0
            )
    """, [module])
    openupgrade.logged_query(env.cr, """
        DELETE FROM account_account_tag_account_move_line_rel r
        WHERE
            account_account_tag_id IN (
                SELECT res_id FROM ir_model_data
                WHERE
                    model = 'account.account.tag' AND
                    module = %s AND
                    name IN ('""" + "','".join(base_tag_xmlids) + """')
            ) AND
            account_move_line_id IN (
                SELECT id FROM account_move_line
                WHERE tax_base_amount <> 0
            )
    """, [module])


def unlink_invalid_tax_tags_from_repartition_lines(
        env, module, base_tag_xmlids, tax_tag_xmlids):
    """ The migration script of the account module assigns all tags of
        the account.tax's tag_ids field to the tag_ids field of the new
        account.tax.repartition.line. However, because each repartition
        line only needs a 'base' - or 'tax' tag, we clean up the other
        tags.
    """
    openupgrade.logged_query(env.cr, """
        DELETE FROM account_account_tag_account_tax_repartition_line_rel r
        WHERE
            account_tax_repartition_line_id IN (
                SELECT id FROM account_tax_repartition_line
                WHERE id = r.account_tax_repartition_line_id
                    AND repartition_type = 'base'
            ) AND
            account_account_tag_id IN (
                SELECT res_id FROM ir_model_data
                WHERE
                    model = 'account.account.tag' AND
                    module = %s AND
                    name IN ('""" + "','".join(tax_tag_xmlids) + """')
            )
    """, [module])
    openupgrade.logged_query(env.cr, """
        DELETE FROM account_account_tag_account_tax_repartition_line_rel r
        WHERE
            account_tax_repartition_line_id IN (
                SELECT id FROM account_tax_repartition_line
                WHERE id = r.account_tax_repartition_line_id
                    AND repartition_type = 'tax'
            ) AND
            account_account_tag_id IN (
                SELECT res_id FROM ir_model_data
                WHERE
                    model = 'account.account.tag' AND
                    module = %s AND
                    name IN ('""" + "','".join(base_tag_xmlids) + """')
            )
    """, [module])
