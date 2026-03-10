# BMD Import/Export for Odoo 18

Export Odoo accounting data to BMD-compatible CSV/Excel format for Austrian accounting software.

**Author:** MPI GmbH, Michael Plöckinger - [www.mpi-erp.at](https://www.mpi-erp.at)

## Features

- **CSV/Excel export** for invoices, credit notes, supplier invoices, and contacts
- **Customizable header mapping** to match different BMD column names
- **Austrian law compliance** (UStG §11, UID, VAT rates 0/10/20%)
- **Odoo.sh installable** (add `openpyxl` to requirements.txt)

## Requirements

- Odoo 18.0
- `account` module
- `l10n_at` (Austrian localization)
- `openpyxl>=3.1.0` (for Excel export)

## Installation

1. Add the module directory to your Odoo addons path
2. Install `openpyxl`: add to `requirements.txt` at repo root for Odoo.sh
3. Update the app list and install "BMD Import/Export"

## Usage

1. **Export Configuration** (Accounting → BMD Export → Export Configuration): Configure delimiter, encoding, and header mappings
2. **Export Invoices** (Accounting → BMD Export → Export Invoices): Select date range and document types, export to CSV or Excel
3. **Export Contacts** (Accounting → BMD Export → Export Contacts): Export customers/suppliers in BMD Personenkonten format

## BMD Format

- **Buchungen**: Tab-delimited CSV with header row (belegnr, belegdat, betrag, steucod, etc.)
- **Personenkonten**: Tab-delimited CSV without header (Kontonummer, Matchcode, Name, Strasse, ...)

## License

LGPL-3.0 or later
