// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { registry } from "@web/core/registry";

/**
 * Tour 1 — single match: scan a product barcode that matches exactly
 * one active MO. Verifies the OWL client action renders, the manual
 * input box accepts Enter, and the MO info strip updates with the
 * matched MO's name.
 */
registry.category("web_tour.tours").add("mrp_scan_app_single_match", {
    steps: () => [
        {
            // Click the header "Scan" button on the MO list view.
            // Opens the MrpScanApp client action (scan-first mode,
            // no MO preselected).
            trigger: ".o_control_panel button[name='action_open_scan_wizard']",
            content: "Click the Scan header button",
            run: "click",
        },
        {
            // Client action root is mounted.
            trigger: ".o_mrp_scan_app",
            content: "MrpScanApp client action is mounted",
        },
        {
            // Type a product barcode in the manual input box and
            // press Enter. The barcode is the test fixture product's
            // barcode (must match the Python-side fixture exactly).
            trigger: ".o_mrp_scan_input",
            content: "Type product barcode and press Enter",
            run: "edit SINGLE_BARCODE_001 && press Enter",
        },
        {
            // After the single RPC round-trip the MO info strip
            // should now show the matched MO's name.
            trigger: ".o_mrp_scan_mo_info:contains('MO:')",
            content: "MO info strip updates with matched MO name",
        },
    ],
});

/**
 * Tour 2 — multi-match: scan a product barcode that matches several
 * active MOs. Verifies that process_barcode_and_dispatch returns an
 * act_window and the client auto-doActions into the filtered
 * mrp.production list (no extra button click — the onchange
 * can't-return-action trade-off is gone).
 */
registry.category("web_tour.tours").add("mrp_scan_app_multi_match", {
    steps: () => [
        {
            trigger: ".o_control_panel button[name='action_open_scan_wizard']",
            content: "Click the Scan header button",
            run: "click",
        },
        {
            trigger: ".o_mrp_scan_app",
            content: "MrpScanApp client action is mounted",
        },
        {
            trigger: ".o_mrp_scan_input",
            content: "Type multi-match barcode and press Enter",
            run: "edit MULTI_BARCODE_001 && press Enter",
        },
        {
            // Auto-doAction into the filtered mrp.production list.
            // Verifies the act_window was returned and executed.
            trigger: ".o_list_renderer table.o_list_table",
            content: "Auto-jumped to the filtered MO list view",
        },
    ],
});

/**
 * Tour 3 — finished SN display + clear. For a serial finished product,
 * scanning the finished SN binds it and shows a display row with a
 * "Clear SN" button. Clicking Clear removes the binding (and the
 * MO's lot_producing_ids for serial products).
 */
registry.category("web_tour.tours").add("mrp_scan_app_finished_sn_display", {
    steps: () => [
        {
            trigger: ".o_control_panel button[name='action_open_scan_wizard']",
            content: "Click the Scan header button",
            run: "click",
        },
        {
            trigger: ".o_mrp_scan_app",
            content: "MrpScanApp client action is mounted",
        },
        {
            // Scan the serial finished product barcode → MO selected +
            // components auto-filled.
            trigger: ".o_mrp_scan_input",
            content: "Scan serial finished product barcode",
            run: "edit SERIAL_FP_BARCODE_001 && press Enter",
        },
        {
            trigger: ".o_mrp_scan_mo_info:contains('MO:')",
            content: "MO info strip appears",
        },
        {
            // Scan a brand-new finished SN → serial one-scan-write binds it.
            trigger: ".o_mrp_scan_input",
            content: "Scan finished SN",
            run: "edit TOUR-FINISHED-SN-001 && press Enter",
        },
        {
            // The finished-SN display row must now show the scanned SN.
            trigger: ".o_mrp_scan_finished_sn:contains('TOUR-FINISHED-SN-001')",
            content: "Finished SN display row shows the scanned SN",
        },
        {
            trigger: ".o_mrp_scan_finished_sn button",
            content: "Click Clear SN",
            run: "click",
        },
        {
            // After clearing, the display row is gone.
            trigger: ".o_mrp_scan_app:not(:has(.o_mrp_scan_finished_sn))",
            content: "Finished SN display row disappears after Clear",
        },
    ],
});
