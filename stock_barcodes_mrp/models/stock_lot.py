# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    # --- Traceability relations ---
    move_line_ids = fields.One2many(
        comodel_name="stock.move.line",
        inverse_name="lot_id",
        string="Move Lines",
    )

    # Lots consumed as raw materials to produce THIS lot (finished lot → material lots)
    consumed_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        string="Consumed Material Lots",
        compute="_compute_traceability",
    )
    # Finished lots produced using THIS lot as a raw material (material lot → finished lots)
    produced_lot_ids = fields.Many2many(
        comodel_name="stock.lot",
        string="Produced Finished Lots",
        compute="_compute_traceability",
    )
    consumed_lot_count = fields.Integer(
        string="Consumed Lots", compute="_compute_traceability",
    )
    produced_lot_count = fields.Integer(
        string="Produced Lots", compute="_compute_traceability",
    )

    @api.depends("move_line_ids.move_id.raw_material_production_id",
                 "move_line_ids.move_id.production_id")
    def _compute_traceability(self):
        Production = self.env["mrp.production"]
        for lot in self:
            consumed_lots = self.env["stock.lot"]
            produced_lots = self.env["stock.lot"]
            # Path 1: via move_line_ids (this lot appears on move lines)
            for line in lot.move_line_ids:
                move = line.move_id
                mo = move.production_id or move.raw_material_production_id
                if not mo:
                    continue
                if move.production_id:
                    # This lot is a finished product → trace consumed materials
                    raw_lines = mo.move_raw_ids.mapped("move_line_ids").filtered(
                        lambda l: l.lot_id
                    )
                    consumed_lots |= raw_lines.mapped("lot_id")
                elif move.raw_material_production_id:
                    # This lot is a raw material → trace produced finished lots
                    finished_lines = mo.move_finished_ids.mapped("move_line_ids").filtered(
                        lambda l: l.lot_id
                    )
                    produced_lots |= finished_lines.mapped("lot_id")
                    produced_lots |= mo.lot_producing_ids
            # Path 2: via lot_producing_ids (finished lot set on MO but not yet
            # in finished move lines, e.g. before posting)
            mos_producing = Production.search([
                ("lot_producing_ids", "in", lot.ids),
            ])
            for mo in mos_producing:
                raw_lines = mo.move_raw_ids.mapped("move_line_ids").filtered(
                    lambda l: l.lot_id
                )
                consumed_lots |= raw_lines.mapped("lot_id")
            # Exclude self from results
            lot.consumed_lot_ids = consumed_lots - lot
            lot.produced_lot_ids = produced_lots - lot
            lot.consumed_lot_count = len(consumed_lots - lot)
            lot.produced_lot_count = len(produced_lots - lot)

    def action_open_consumed_lots(self):
        """Open the list of material lots consumed to produce this lot."""
        self.ensure_one()
        return {
            "name": _("Consumed Material Lots for %s") % self.display_name,
            "type": "ir.actions.act_window",
            "res_model": "stock.lot",
            "view_mode": "list,form",
            "domain": [("id", "in", self.consumed_lot_ids.ids)],
            "context": {"create": False, "edit": False},
        }

    def action_open_produced_lots(self):
        """Open the list of finished lots produced using this lot."""
        self.ensure_one()
        return {
            "name": _("Produced Finished Lots from %s") % self.display_name,
            "type": "ir.actions.act_window",
            "res_model": "stock.lot",
            "view_mode": "list,form",
            "domain": [("id", "in", self.produced_lot_ids.ids)],
            "context": {"create": False, "edit": False},
        }
