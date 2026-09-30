# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

"""Backfill barcode_scan_source_location for existing picking types.

Runs on upgrade to 19.0.1.1.0 (post_init_hook only fires on install, so
existing installations need this migration to pick up the backfill).

Source-location scanning was mandatory before the per-picking-type
config existed; set it True on every existing picking type to preserve
that behaviour. barcode_scan_dest_location stays False (destination
scanning was never required before).
"""


def migrate(cr, version):
    cr.execute(
        "UPDATE stock_picking_type "
        "SET barcode_scan_source_location = TRUE "
        "WHERE barcode_scan_source_location IS NULL "
        "OR barcode_scan_source_location = FALSE"
    )
