# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""Carry the old package_scan_intent over to the new scan_mode field.

package_scan_intent is now a computed mirror of scan_mode, so its column
may already be gone when this migration runs. Only touch it when both
columns exist, and never fail an upgrade because of it.
"""


def migrate(cr, version):
    cr.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'wiz_stock_barcodes_picking' "
        "AND column_name IN ('package_scan_intent', 'scan_mode')"
    )
    columns = {row[0] for row in cr.fetchall()}
    if not {"package_scan_intent", "scan_mode"} <= columns:
        return
    cr.execute(
        "UPDATE wiz_stock_barcodes_picking "
        "SET scan_mode = CASE WHEN package_scan_intent = 'pack' "
        "THEN 'pack' ELSE 'default' END "
        "WHERE package_scan_intent IS NOT NULL "
        "AND (scan_mode IS NULL OR scan_mode = '')"
    )
