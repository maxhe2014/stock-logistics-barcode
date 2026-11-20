// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { rpc } from "@web/core/network/rpc";

// One-time cleanup for every backend page: earlier builds enabled Web
// Responsive's "redirect home" preference, which makes its apps overlay
// auto-open on top of scan/form pages. Reset it once per session.
if (!sessionStorage.getItem("scan_home_pref_reset")) {
    sessionStorage.setItem("scan_home_pref_reset", "1");
    rpc("/web/dataset/call_kw", {
        model: "stock.barcodes.workbench",
        method: "set_redirect_home",
        args: [false],
        kwargs: {},
    }).catch(() => {});
}

/**
 * Global helper: the workbench nine-dot navigates to /odoo and drops a
 * one-shot flag in sessionStorage. The Web Responsive apps-grid overlay is
 * client-side, so open it here once the navbar (and its nine-dot button)
 * is mounted. This avoids toggling the user's "redirect home" preference,
 * which made the overlay auto-open on top of scan/form pages.
 */
function openAppsMenuOnce() {
    if (sessionStorage.getItem("scan_open_apps_menu") !== "1") {
        return true;
    }
    const button = document.querySelector(
        ".o_grid_apps_menu__button, .o_navbar_apps_menu button"
    );
    if (!button) {
        return false;
    }
    sessionStorage.removeItem("scan_open_apps_menu");
    button.click();
    return true;
}

if (!openAppsMenuOnce()) {
    let tries = 0;
    const timer = setInterval(() => {
        tries += 1;
        if (openAppsMenuOnce() || tries >= 40) {
            clearInterval(timer);
        }
    }, 250);
}
