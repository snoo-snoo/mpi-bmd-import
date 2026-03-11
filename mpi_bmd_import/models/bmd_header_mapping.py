# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models


class BmdHeaderMapping(models.Model):
    """Configurable mapping between BMD column names and Odoo fields."""

    _name = "bmd.header.mapping"
    _description = "BMD Header Mapping"
    _order = "sequence, id"

    config_id = fields.Many2one(
        "bmd.export.config",
        string="Export Config",
        ondelete="cascade",
        required=True,
    )
    sequence = fields.Integer(default=10)
    bmd_field_name = fields.Char(
        string="BMD Column Name",
        required=True,
        help="Column name in BMD import file (e.g. belegnr, Kontonummer)",
    )
    odoo_field_id = fields.Many2one(
        "ir.model.fields",
        string="Odoo Field (select)",
        domain="[('model', '=', target_model), ('ttype', 'not in', ['one2many', 'many2many'])]",
        ondelete="set null",
        help="Pick an Odoo field from the dropdown. For dotted paths "
             "(e.g. property_account_receivable_id.id) or invoice data "
             "keys, edit the text field directly instead.",
    )
    odoo_field_name = fields.Char(
        string="Odoo Field",
        required=True,
        help="Technical field name in Odoo model (e.g. name, ref). "
             "Supports dotted paths for related fields (e.g. "
             "property_account_receivable_id.display_name).",
    )
    export_type = fields.Selection(
        [
            ("invoices", "Invoices / Credit Notes"),
            ("contacts", "Contacts"),
        ],
        string="Export Type",
        required=True,
    )
    target_model = fields.Char(
        string="Model",
        compute="_compute_target_model",
        store=True,
    )

    @api.depends("export_type")
    def _compute_target_model(self):
        for rec in self:
            rec.target_model = (
                "account.move" if rec.export_type == "invoices" else "res.partner"
            )

    @api.onchange("odoo_field_id")
    def _onchange_odoo_field_id(self):
        if self.odoo_field_id:
            self.odoo_field_name = self.odoo_field_id.name
