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
    odoo_field_name = fields.Char(
        string="Odoo Field",
        required=True,
        help="Technical field name in Odoo model (e.g. name, ref)",
    )
    export_type = fields.Selection(
        [
            ("invoices", "Invoices / Credit Notes"),
            ("contacts", "Contacts"),
        ],
        string="Export Type",
        required=True,
    )
    model = fields.Char(
        string="Model",
        compute="_compute_model",
        store=True,
    )

    @api.depends("export_type")
    def _compute_model(self):
        for rec in self:
            rec.model = (
                "account.move" if rec.export_type == "invoices" else "res.partner"
            )
