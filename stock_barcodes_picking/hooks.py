# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

BARCODE_PARAM = "barcode.max_time_between_keys_in_ms"
BACKUP_PARAM = "stock_barcodes_picking.barcode_max_time_backup"
DEFAULT_MAX_TIME = "1500"


def post_init_hook(env):
    """Backfill picking-type settings and the barcode timing parameter.

    Source-location scanning was mandatory before the feature existed, so
    existing picking types are set to True to keep the pre-feature
    behaviour. ``barcode_scan_dest_location`` stays False.

    The barcode timing parameter is written here (instead of a data
    ``<function>``) so the previous value can be stored for
    :func:`uninstall_hook`. The value is only set when the parameter does
    not exist yet, so an administrator's explicit setting is preserved.
    """
    picking_types = env["stock.picking.type"].with_context(
        active_test=False
    ).search([])
    picking_types.filtered(
        lambda pt: not pt.barcode_scan_source_location
    ).write({"barcode_scan_source_location": True})

    params = env["ir.config_parameter"].sudo()
    backup = params.search([("key", "=", BACKUP_PARAM)], limit=1)
    if not backup:
        current = params.get_param(BARCODE_PARAM)
        params.set_param(BACKUP_PARAM, current if current else "")
        if not current:
            params.set_param(BARCODE_PARAM, DEFAULT_MAX_TIME)


def uninstall_hook(env):
    """Remove every database trace left by this module.

    Tables of module models, columns added to core models and records with
    an XML id are removed by Odoo itself. The only value written outside
    that mechanism is ``barcode.max_time_between_keys_in_ms`` (owned by
    the ``barcodes`` dependency), restored to its pre-install value here.
    """
    params = env["ir.config_parameter"].sudo()
    backup = params.search([("key", "=", BACKUP_PARAM)], limit=1)
    if not backup:
        # Installs created before the backup mechanism existed always wrote
        # the default value, so remove it when it is still unchanged.
        if params.get_param(BARCODE_PARAM) == DEFAULT_MAX_TIME:
            params.search([("key", "=", BARCODE_PARAM)]).unlink()
        return
    if backup.value:
        params.set_param(BARCODE_PARAM, backup.value)
    else:
        params.search([("key", "=", BARCODE_PARAM)]).unlink()
    backup.unlink()
