# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import fields, models

_DELIMITER_MAP = {"tab": "\t", "semicolon": ";", "comma": ","}


class BmdExportConfig(models.Model):
    """Export settings for BMD format (delimiter, encoding, mappings)."""

    _name = "bmd.export.config"
    _description = "BMD Export Configuration"

    name = fields.Char(string="Name", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    delimiter = fields.Selection(
        [
            ("tab", "Tab"),
            ("semicolon", "Semicolon"),
            ("comma", "Comma"),
        ],
        string="CSV Delimiter",
        default="semicolon",
        help="BMD standard delimiter; all field values are double-quoted.",
    )
    encoding = fields.Selection(
        [
            ("utf-8", "UTF-8"),
            ("utf-8-sig", "UTF-8 with BOM"),
            ("cp1252", "Windows-1252"),
        ],
        string="Encoding",
        default="utf-8",
    )
    header_mapping_ids = fields.One2many(
        "bmd.header.mapping",
        "config_id",
        string="Header Mappings",
    )

    def get_delimiter_char(self):
        """Return the actual delimiter character for CSV writing."""
        self.ensure_one()
        return _DELIMITER_MAP[self.delimiter]
