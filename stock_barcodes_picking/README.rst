======================
Stock Barcodes Picking
======================

This module provides a touch-friendly barcode scanning screen for stock
transfers. Operators scan the source location, destination location,
product barcodes and serial/lot numbers; the screen keeps the scanned
values in sync with the transfer and validates them immediately.

Highlights:

* scan source/destination locations, products and serial/lot numbers;
* keep the selected product row highlighted so a whole batch of serial
  numbers can be scanned without re-selecting the product;
* select the product automatically when a serial number is scanned;
* detect unusable serial numbers at scan time (wrong location, already
  delivered, reserved by another transfer, duplicated);
* configurable over-receipt policy per operation type (allow, warn or
  forbid).

Configuration
-------------

Barcode timing
~~~~~~~~~~~~~~

Phones, Bluetooth scanners and soft keyboards may send characters
slowly, which splits a long barcode into several chunks. Increasing the
system parameter ``barcode.max_time_between_keys_in_ms`` fixes this.

The module writes ``1500`` when it is installed. The value is only
written on install, so an administrator's later change is preserved on
module upgrade.

* *Settings > Technical > Parameters > System Parameters*;
* key: ``barcode.max_time_between_keys_in_ms``;
* value: ``1500`` (milliseconds).

With an input device that sends an Enter/Tab terminator the scan is
submitted immediately and this value has no visible impact. Devices
without terminator wait for this timeout before submitting, so do not
raise it above ``2000`` unless required.

Usage
-----

Barcode scanning
~~~~~~~~~~~~~~~~

#. Open a transfer and press *Scan barcodes*.
#. Scan the source location, then the destination location (when these
   steps are enabled on the operation type).
#. Scan a product barcode, or scan a serial/lot number directly: the
   product is selected automatically.
#. Scan serial/lot numbers; the selected row stays highlighted until
   another row is clicked or another product barcode is scanned.
#. Press *Validate* to process the transfer.

Over-receipt policy
~~~~~~~~~~~~~~~~~~~

On the operation type (*Barcode* tab) the *Excess Scan Policy* field
controls what happens when the scanned quantity exceeds the demand:

* *Allow*: the extra quantity is added with an information message;
* *Warn and Require Confirmation* (default): the operator must press
  *Force* to add the extra quantity;
* *Forbid*: the scan is rejected.

Credits
-------

Authors
~~~~~~~

* OpenViking

License
~~~~~~~

AGPL-3.0 or later.
