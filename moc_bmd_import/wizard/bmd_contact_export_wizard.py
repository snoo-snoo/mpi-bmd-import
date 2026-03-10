# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import csv
import io
from base64 import b64encode

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BmdContactExportWizard(models.TransientModel):
    _name = "bmd.contact.export.wizard"
    _description = "BMD Contact Export Wizard"

    config_id = fields.Many2one(
        "bmd.export.config",
        string="Export Config",
        required=True,
        default=lambda self: self._default_config(),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        help="Used to restrict export config to current company.",
    )
    export_format = fields.Selection(
        [
            ("csv", "CSV"),
            ("xlsx", "Excel"),
        ],
        string="Format",
        default="csv",
        required=True,
    )
    partner_type = fields.Selection(
        [
            ("customer", "Customers only"),
            ("supplier", "Suppliers only"),
            ("both", "Customers and Suppliers"),
        ],
        string="Partner Type",
        default="both",
        required=True,
    )
    data = fields.Binary(string="Generated File", readonly=True)
    filename = fields.Char(string="Filename", readonly=True)

    def _default_config(self):
        """Return first config for current company only; no cross-company fallback."""
        return self.env["bmd.export.config"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )

    def _get_partners(self):
        domain = []
        if self.partner_type == "customer":
            domain.append(("customer_rank", ">", 0))
        elif self.partner_type == "supplier":
            domain.append(("supplier_rank", ">", 0))
        else:
            domain.append("|")
            domain.append(("customer_rank", ">", 0))
            domain.append(("supplier_rank", ">", 0))
        return self.env["res.partner"].search(domain)

    def _get_contact_mappings(self):
        return self.config_id.header_mapping_ids.filtered(
            lambda m: m.export_type == "contacts"
        ).sorted("sequence")

    def _get_partner_value(self, partner, field_name):
        """Get value for a partner field, handling special cases."""
        if field_name == "country_id":
            return partner.country_id.code or ""
        return getattr(partner, field_name, "") or ""

    def _build_csv_rows(self, partners):
        """Build Personenkonten rows. No header row per BMD pr08i config."""
        mappings = self._get_contact_mappings()
        if not mappings:
            return []

        rows = []
        for partner in partners:
            row = []
            for mapping in mappings:
                val = self._get_partner_value(partner, mapping.odoo_field_name)
                row.append(str(val) if val is not None else "")
            rows.append(row)
        return rows

    def _export_csv(self, partners):
        """Export to CSV."""
        rows = self._build_csv_rows(partners)
        delimiter = self.config_id.get_delimiter_char()
        encoding = self.config_id.encoding

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(row)

        return output.getvalue().encode(encoding, errors="replace")

    def _export_xlsx(self, partners):
        """Export to Excel using openpyxl."""
        try:
            from openpyxl import Workbook
        except ImportError:
            raise UserError(
                _("Excel export requires openpyxl. Add it to requirements.txt.")
            ) from None

        rows = self._build_csv_rows(partners)
        wb = Workbook()
        ws = wb.active
        ws.title = "Personenkonten"
        for row in rows:
            ws.append(row)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def action_export(self):
        self.ensure_one()
        if not self.config_id:
            raise UserError(
                _(
                    "No BMD export configuration for your company. "
                    "Please create one under Accounting → BMD Export → Export Configuration."
                )
            )
        partners = self._get_partners()
        if not partners:
            raise UserError(_("No partners match the selected criteria."))

        if self.export_format == "csv":
            data = self._export_csv(partners)
            ext = "csv"
        else:
            data = self._export_xlsx(partners)
            ext = "xlsx"

        self.write(
            {
                "data": b64encode(data),
                "filename": f"bmd_personenkonten.{ext}",
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
