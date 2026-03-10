# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

{
    "name": "BMD Import/Export",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "summary": "Export Odoo data to BMD-compatible CSV/Excel format for Austrian accounting",
    "author": "MPI GmbH, Michael Plöckinger - www.mpi-erp.at",
    "website": "https://www.mpi-erp.at",
    "license": "LGPL-3",
    "depends": ["account", "l10n_at"],
    "data": [
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/bmd_default_mappings.xml",
        "views/bmd_export_config_views.xml",
        "views/bmd_invoice_export_wizard_views.xml",
        "views/bmd_contact_export_wizard_views.xml",
        "views/bmd_menu_views.xml",
    ],
    "installable": True,
    "application": False,
}
