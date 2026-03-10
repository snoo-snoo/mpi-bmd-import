# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import calendar
import csv
import io
import logging
import re
from base64 import b64encode
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BMD_STEUCOD_SALE = 3
BMD_STEUCOD_PURCHASE = 0
BMD_STEUCOD_MIXED = 88

_SALE_ACCOUNT_TYPES = ("income", "income_other")
_PURCHASE_ACCOUNT_TYPES = (
    "expense", "expense_other", "expense_depreciation", "expense_direct_cost",
)


class BmdInvoiceExportWizard(models.TransientModel):
    _name = "bmd.invoice.export.wizard"
    _description = "BMD Invoice Export Wizard"

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
    date_from = fields.Date(string="From Date", required=True)
    date_to = fields.Date(string="To Date", required=True)
    move_types = fields.Selection(
        [
            ("all", "All (Invoices + Credit Notes)"),
            ("out_invoice", "Customer Invoices only"),
            ("out_refund", "Customer Credit Notes only"),
            ("in_invoice", "Supplier Invoices only"),
            ("in_refund", "Supplier Credit Notes only"),
        ],
        string="Document Types",
        default="all",
        required=True,
    )
    data = fields.Binary(string="Generated File", readonly=True)
    filename = fields.Char(string="Filename", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        res.setdefault("date_from", today.replace(month=1, day=1))
        res.setdefault("date_to", today)
        return res

    def _default_config(self):
        """Return first config for current company; if none, use shared config (no company)."""
        config = self.env["bmd.export.config"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        if not config:
            config = self.env["bmd.export.config"].search(
                [("company_id", "=", False)], limit=1
            )
        return config

    def _get_moves(self):
        domain = [
            ("company_id", "=", self.env.company.id),
            ("state", "=", "posted"),
            ("move_type", "in", ["out_invoice", "out_refund", "in_invoice", "in_refund"]),
            ("invoice_date", ">=", self.date_from),
            ("invoice_date", "<=", self.date_to),
        ]
        if self.move_types != "all":
            domain.append(("move_type", "=", self.move_types))
        return self.env["account.move"].search(domain, order="invoice_date, name")

    def _get_bmd_symbol(self, move):
        if move.move_type in ("out_invoice", "out_refund"):
            return "AR"
        return "ER"

    def _get_bmd_steucod(self, move):
        if move.move_type in ("out_invoice", "out_refund"):
            return BMD_STEUCOD_SALE
        return BMD_STEUCOD_PURCHASE

    def _get_belegnr_numeric(self, name):
        """Extract numeric part from move name (e.g. INV/2024/0001 -> 1)."""
        if not name:
            return "0"
        nums = re.findall(r"\d+", str(name))
        return nums[-1] if nums else "0"

    def _date_to_bmd(self, date_val):
        """Convert date to BMD format YYYYMMDD."""
        if not date_val:
            return ""
        if isinstance(date_val, datetime):
            date_val = date_val.date()
        return date_val.strftime("%Y%m%d")

    def _get_move_line_data(self, move):
        """
        Extract BMD-relevant data from a move.
        Returns one row per revenue/expense line (correct accounting per account).
        Tax total is attributed to the first row only to avoid double-counting.
        """
        symbol = self._get_bmd_symbol(move)
        is_refund = move.move_type in ("out_refund", "in_refund")
        is_sale = move.move_type in ("out_invoice", "out_refund")

        income_lines = move.line_ids.filtered(
            lambda l: l.account_id.account_type in _SALE_ACCOUNT_TYPES
        )
        expense_lines = move.line_ids.filtered(
            lambda l: l.account_id.account_type in _PURCHASE_ACCOUNT_TYPES
        )
        tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)

        if is_sale:
            main_lines = income_lines
        else:
            main_lines = expense_lines

        if not main_lines:
            return []

        tax_balance = sum(tax_lines.mapped("balance"))
        # BMD sign: AR revenue / ER-Gutschrift = negative; ER / AR-Gutschrift = positive
        if is_sale and not is_refund:
            tax_balance = -abs(tax_balance)
        elif is_sale and is_refund:
            tax_balance = abs(tax_balance)
        elif not is_sale and not is_refund:
            tax_balance = abs(tax_balance)
        else:
            tax_balance = -abs(tax_balance)

        partner = move.partner_id
        gkto = partner.bmd_kontonummer if partner else ""
        steucod = self._get_bmd_steucod(move)

        inv_date = move.invoice_date or move.date
        last_day = calendar.monthrange(inv_date.year, inv_date.month)[1]
        buchdat = inv_date.replace(day=last_day)

        result = []
        for idx, line in enumerate(main_lines):
            net_balance = line.balance
            if is_sale and not is_refund:
                net_balance = -abs(net_balance)
            elif is_sale and is_refund:
                net_balance = abs(net_balance)
            elif not is_sale and not is_refund:
                net_balance = abs(net_balance)
            else:
                net_balance = -abs(net_balance)

            bucod = 2 if net_balance < 0 else 1
            account = line.account_id
            konto = account.code or str(account.id)

            line_tax_rates = set()
            for tax in line.tax_ids:
                if tax.amount_type == "percent":
                    line_tax_rates.add(int(tax.amount))
            if len(line_tax_rates) > 1:
                mwst = BMD_STEUCOD_MIXED
            elif line_tax_rates:
                mwst = list(line_tax_rates)[0]
            else:
                mwst = 0

            # Full tax amount on first line only; 0 on subsequent lines
            line_tax = tax_balance if idx == 0 else 0.0
            text = (line.name or move.name or "")[:50]

            result.append({
                "belegnr": self._get_belegnr_numeric(move.name),
                "belegdat": self._date_to_bmd(move.invoice_date),
                "extbelegnr": (move.ref or "")[:20],
                "betrag": f"{net_balance:.2f}".replace(".", ","),
                "bucod": str(bucod),
                "steucod": str(steucod),
                "gkto": gkto,
                "konto": konto,
                "mwst": str(mwst),
                "steuer": f"{line_tax:.2f}".replace(".", ","),
                "text": text,
                "gegenbuchkz": "E",
                "verbuchkz": "A",
                "kost": self._get_belegnr_numeric(move.name),
                "symbol": symbol,
                "buchdat": self._date_to_bmd(buchdat),
            })
        return result

    def _build_csv_rows(self, moves):
        """Build Buchungen rows with header."""
        mappings = self.config_id.header_mapping_ids.filtered(
            lambda m: m.export_type == "invoices"
        ).sorted("sequence")
        if not mappings:
            # Fallback: use default column order
            columns = [
                "belegnr", "belegdat", "extbelegnr", "betrag", "bucod", "steucod",
                "gkto", "konto", "mwst", "steuer", "text", "gegenbuchkz",
                "verbuchkz", "kost", "symbol", "buchdat",
            ]
        else:
            columns = [m.bmd_field_name for m in mappings]

        rows = [columns]
        for move in moves:
            for row_data in self._get_move_line_data(move):
                row = [row_data.get(col, "") for col in columns]
                rows.append(row)
        return rows

    def _export_csv(self, moves):
        """Export to CSV with header row."""
        rows = self._build_csv_rows(moves)
        delimiter = self.config_id.get_delimiter_char()
        encoding = self.config_id.encoding

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(row)

        return output.getvalue().encode(encoding, errors="replace")

    def _export_xlsx(self, moves):
        """Export to Excel using openpyxl."""
        try:
            from openpyxl import Workbook
        except ImportError:
            raise UserError(
                _("Excel export requires openpyxl. Add it to requirements.txt.")
            ) from None

        rows = self._build_csv_rows(moves)
        wb = Workbook()
        ws = wb.active
        ws.title = "Buchungen"
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
        if self.date_from > self.date_to:
            raise UserError(
                _("'From Date' must be earlier than or equal to 'To Date'.")
            )
        moves = self._get_moves()
        if not moves:
            raise UserError(
                _("No posted invoices match the selected criteria.")
            )

        _logger.info(
            "BMD invoice export: %d moves, %s–%s, format=%s, user=%s",
            len(moves), self.date_from, self.date_to,
            self.export_format, self.env.user.login,
        )

        if self.export_format == "csv":
            data = self._export_csv(moves)
            ext = "csv"
        else:
            data = self._export_xlsx(moves)
            ext = "xlsx"

        self.write(
            {
                "data": b64encode(data),
                "filename": f"bmd_buchungen.{ext}",
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
