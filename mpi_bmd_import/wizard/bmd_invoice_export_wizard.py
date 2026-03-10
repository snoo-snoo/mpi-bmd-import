# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import calendar
import csv
import io
import logging
import re
import zipfile
from base64 import b64decode, b64encode
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BMD_STEUCOD_SALE = 3
BMD_STEUCOD_PURCHASE = 0
BMD_STEUCOD_MIXED = 88

_SALE_ACCOUNT_TYPES = ("income", "income_other")
_PURCHASE_ACCOUNT_TYPES = ("expense", "expense_depreciation", "expense_direct_cost")


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
    export_mode = fields.Selection(
        [
            ("per_line", "One row per account line"),
            ("per_invoice", "One row per invoice (Netto / Brutto / Steuer)"),
        ],
        string="Export Mode",
        default="per_invoice",
        required=True,
    )
    include_pdfs = fields.Boolean(
        string="Include PDF documents",
        default=False,
        help="Attach each invoice/credit note as PDF and add a beleglink "
             "column to the CSV. Output becomes a ZIP archive.",
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

    def _sanitize_filename(self, name):
        """Turn an invoice name like 'INV/2024/0001' into 'INV_2024_0001'."""
        return re.sub(r'[^\w\-.]', '_', str(name or "document").strip())

    def _get_pdf_filename(self, move):
        """Return a unique PDF filename for a move, e.g. 'AR_INV_2024_0001.pdf'."""
        symbol = self._get_bmd_symbol(move)
        safe_name = self._sanitize_filename(move.name)
        return f"{symbol}_{safe_name}.pdf"

    def _collect_pdfs(self, moves):
        """Batch-collect invoice PDFs, reusing cached report attachments.

        Odoo's invoice report caches rendered PDFs as ir.attachment records.
        This method retrieves cached ones in bulk (single query) and only
        renders the remaining invoices in one batched wkhtmltopdf call
        instead of one call per invoice.
        """
        report_ref = "account.account_invoices"
        report = self.env["ir.actions.report"]._get_report(report_ref)
        result = {}

        cached_atts = self.env["ir.attachment"].search([
            ("res_model", "=", "account.move"),
            ("res_id", "in", moves.ids),
            ("name", "=like", "%.pdf"),
        ])
        att_by_move = {}
        for att in cached_atts:
            att_by_move.setdefault(att.res_id, att)

        to_render = self.env["account.move"]
        for move in moves:
            if move.id in att_by_move:
                result[move.id] = b64decode(att_by_move[move.id].datas)
            else:
                to_render |= move

        if not to_render:
            _logger.info("BMD PDF export: all %d PDFs served from cache.", len(result))
            return result

        _logger.info(
            "BMD PDF export: %d cached, %d to render.",
            len(result), len(to_render),
        )

        try:
            self.env["ir.actions.report"]._render_qweb_pdf(
                report_ref, to_render.ids,
            )
            for move in to_render:
                att = report._retrieve_attachment(move)
                if att:
                    result[move.id] = b64decode(att.datas)
                else:
                    _logger.warning(
                        "PDF attachment not found for %s after batch render.",
                        move.name,
                    )
        except Exception:
            _logger.warning(
                "Batch PDF render failed, falling back to individual rendering.",
                exc_info=True,
            )
            for move in to_render:
                try:
                    pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
                        report_ref, [move.id],
                    )
                    result[move.id] = pdf_content
                except Exception:
                    _logger.warning(
                        "Could not generate PDF for %s, skipping.",
                        move.name, exc_info=True,
                    )

        return result

    def _get_bmd_sign(self, balance, is_sale, is_refund):
        """Apply BMD sign convention to a balance amount."""
        if is_sale and not is_refund:
            return -abs(balance)
        elif is_sale and is_refund:
            return abs(balance)
        elif not is_sale and not is_refund:
            return abs(balance)
        return -abs(balance)

    def _get_main_and_tax_lines(self, move):
        """Return (main_lines, tax_lines, is_sale, is_refund) for a move."""
        is_refund = move.move_type in ("out_refund", "in_refund")
        is_sale = move.move_type in ("out_invoice", "out_refund")
        income_lines = move.line_ids.filtered(
            lambda l: l.account_id.account_type in _SALE_ACCOUNT_TYPES
        )
        expense_lines = move.line_ids.filtered(
            lambda l: l.account_id.account_type in _PURCHASE_ACCOUNT_TYPES
        )
        tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
        main_lines = income_lines if is_sale else expense_lines
        return main_lines, tax_lines, is_sale, is_refund

    def _collect_tax_rates(self, lines):
        """Return the aggregated MwSt value across all lines."""
        all_rates = set()
        for line in lines:
            for tax in line.tax_ids:
                if tax.amount_type == "percent":
                    all_rates.add(int(tax.amount))
        if len(all_rates) > 1:
            return BMD_STEUCOD_MIXED
        return all_rates.pop() if all_rates else 0

    def _get_common_fields(self, move, is_sale, is_refund):
        """Return dict of fields shared by both export modes."""
        partner = move.partner_id
        inv_date = move.invoice_date or move.date
        last_day = calendar.monthrange(inv_date.year, inv_date.month)[1]
        vals = {
            "belegnr": self._get_belegnr_numeric(move.name),
            "belegdat": self._date_to_bmd(move.invoice_date),
            "extbelegnr": (move.ref or "")[:20],
            "steucod": str(self._get_bmd_steucod(move)),
            "gkto": partner.bmd_kontonummer if partner else "",
            "gegenbuchkz": "E",
            "verbuchkz": "A",
            "kost": self._get_belegnr_numeric(move.name),
            "symbol": self._get_bmd_symbol(move),
            "buchdat": self._date_to_bmd(inv_date.replace(day=last_day)),
        }
        if self.include_pdfs:
            vals["beleglink"] = f"belege/{self._get_pdf_filename(move)}"
        return vals

    def _get_move_line_data(self, move):
        """
        One row per revenue/expense line (correct accounting per account).
        Tax total is attributed to the first row only to avoid double-counting.
        """
        main_lines, tax_lines, is_sale, is_refund = self._get_main_and_tax_lines(move)
        if not main_lines:
            return []

        tax_balance = self._get_bmd_sign(
            sum(tax_lines.mapped("balance")), is_sale, is_refund,
        )
        common = self._get_common_fields(move, is_sale, is_refund)

        result = []
        for idx, line in enumerate(main_lines):
            net_balance = self._get_bmd_sign(line.balance, is_sale, is_refund)
            mwst = self._collect_tax_rates(line)
            line_tax = tax_balance if idx == 0 else 0.0

            result.append({
                **common,
                "betrag": f"{net_balance:.2f}".replace(".", ","),
                "bucod": str(2 if net_balance < 0 else 1),
                "konto": line.account_id.code or str(line.account_id.id),
                "mwst": str(mwst),
                "steuer": f"{line_tax:.2f}".replace(".", ","),
                "text": (line.name or move.name or "")[:50],
            })
        return result

    def _get_move_summary_data(self, move):
        """One aggregated row per invoice with netto, brutto, and steuer."""
        main_lines, tax_lines, is_sale, is_refund = self._get_main_and_tax_lines(move)
        if not main_lines:
            return []

        netto = self._get_bmd_sign(sum(main_lines.mapped("balance")), is_sale, is_refund)
        steuer = self._get_bmd_sign(sum(tax_lines.mapped("balance")), is_sale, is_refund)
        brutto = netto + steuer

        primary_line = max(main_lines, key=lambda l: abs(l.balance))
        common = self._get_common_fields(move, is_sale, is_refund)

        return [{
            **common,
            "netto": f"{netto:.2f}".replace(".", ","),
            "brutto": f"{brutto:.2f}".replace(".", ","),
            "betrag": f"{netto:.2f}".replace(".", ","),
            "bucod": str(2 if netto < 0 else 1),
            "konto": primary_line.account_id.code or str(primary_line.account_id.id),
            "mwst": str(self._collect_tax_rates(main_lines)),
            "steuer": f"{steuer:.2f}".replace(".", ","),
            "text": (move.ref or move.name or "")[:50],
        }]

    def _get_row_data(self, move):
        """Dispatch to per-line or per-invoice depending on export_mode."""
        if self.export_mode == "per_invoice":
            return self._get_move_summary_data(move)
        return self._get_move_line_data(move)

    def _get_columns(self):
        """Return ordered column list for the CSV header."""
        mappings = self.config_id.header_mapping_ids.filtered(
            lambda m: m.export_type == "invoices"
        ).sorted("sequence")
        if mappings:
            columns = [m.bmd_field_name for m in mappings]
        elif self.export_mode == "per_invoice":
            columns = [
                "belegnr", "belegdat", "extbelegnr", "netto", "brutto",
                "steuer", "bucod", "steucod", "gkto", "konto", "mwst",
                "text", "gegenbuchkz", "verbuchkz", "kost", "symbol",
                "buchdat",
            ]
        else:
            columns = [
                "belegnr", "belegdat", "extbelegnr", "betrag", "bucod",
                "steucod", "gkto", "konto", "mwst", "steuer", "text",
                "gegenbuchkz", "verbuchkz", "kost", "symbol", "buchdat",
            ]
        if self.include_pdfs and "beleglink" not in columns:
            columns.append("beleglink")
        return columns

    def _build_csv_rows(self, moves):
        """Build Buchungen rows with header."""
        columns = self._get_columns()
        rows = [columns]
        for move in moves:
            for row_data in self._get_row_data(move):
                row = [row_data.get(col, "") for col in columns]
                rows.append(row)
        return rows

    def _export_csv(self, moves):
        """Export to CSV with header row."""
        rows = self._build_csv_rows(moves)
        delimiter = self.config_id.get_delimiter_char()
        encoding = self.config_id.encoding

        output = io.StringIO()
        writer = csv.writer(output, delimiter=delimiter, quoting=csv.QUOTE_ALL)
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

    def _export_zip(self, moves):
        """Bundle CSV/XLSX + individual invoice PDFs into a ZIP archive."""
        ext = "csv" if self.export_format == "csv" else "xlsx"
        if self.export_format == "csv":
            data_file = self._export_csv(moves)
        else:
            data_file = self._export_xlsx(moves)

        pdf_map = self._collect_pdfs(moves)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"bmd_buchungen.{ext}", data_file)
            for move in moves:
                pdf_bytes = pdf_map.get(move.id)
                if pdf_bytes:
                    zf.writestr(
                        f"belege/{self._get_pdf_filename(move)}", pdf_bytes,
                    )
        return buf.getvalue()

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
            "BMD invoice export: %d moves, %s–%s, format=%s, pdfs=%s, user=%s",
            len(moves), self.date_from, self.date_to,
            self.export_format, self.include_pdfs, self.env.user.login,
        )

        if self.include_pdfs:
            data = self._export_zip(moves)
            filename = "bmd_buchungen.zip"
        elif self.export_format == "csv":
            data = self._export_csv(moves)
            filename = "bmd_buchungen.csv"
        else:
            data = self._export_xlsx(moves)
            filename = "bmd_buchungen.xlsx"

        self.write({"data": b64encode(data), "filename": filename})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
