# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

import re

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    bmd_matchcode = fields.Char(
        string="BMD Matchcode",
        compute="_compute_bmd_matchcode",
        store=True,
    )
    bmd_kontonummer = fields.Char(
        string="BMD Kontonummer",
        compute="_compute_bmd_kontonummer",
        store=True,
    )

    @api.depends("name")
    def _compute_bmd_matchcode(self):
        """First 10 chars of name in uppercase for BMD Matchcode."""
        for partner in self:
            name = (partner.name or "").upper()
            for old, new in [("Ä", "A"), ("Ö", "O"), ("Ü", "U"), ("ß", "SS")]:
                name = name.replace(old, new)
            partner.bmd_matchcode = name[:10] if name else ""

    @api.depends("ref", "customer_rank", "supplier_rank", "id")
    def _compute_bmd_kontonummer(self):
        """5-9 digit account number: use ref if numeric, else generate from id."""
        for partner in self:
            if partner.ref and re.match(r"^\d{5,9}$", str(partner.ref).strip()):
                partner.bmd_kontonummer = str(partner.ref).strip()
            else:
                prefix = (
                    100000
                    if partner.customer_rank or not partner.supplier_rank
                    else 200000
                )
                partner.bmd_kontonummer = str(prefix + partner.id)[:9]
