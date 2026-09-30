# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    """Backfill barcode_scan_source_location for existing picking types.

    New Boolean columns default to NULL (rendered as False) on existing
    rows, which would silently disable source-location scanning for
    picking types created before this module introduced the config.
    Source-location scanning was mandatory before the feature existed,
    so set it True on every existing picking type to preserve the
    pre-feature behaviour. ``barcode_scan_dest_location`` stays False
    (destination scanning was never required before).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    picking_types = env["stock.picking.type"].with_context(
        active_test=False
    ).search([])
    # Only flip False → True; leave any explicitly-configured rows alone.
    picking_types.filtered(
        lambda pt: not pt.barcode_scan_source_location
    ).write({"barcode_scan_source_location": True})
