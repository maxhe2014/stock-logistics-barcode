Barcode scanning
================

#. Open a transfer and press *Scan barcodes*.
#. Scan the source location, then the destination location (when these
   steps are enabled on the operation type).
#. Scan a product barcode, or scan a serial/lot number directly: the
   product is selected automatically.
#. Scan serial/lot numbers; the selected row stays highlighted until
   another row is clicked or another product barcode is scanned.
#. Press *Validate* to process the transfer.

Over-receipt policy
===================

On the operation type (*Barcode* tab) the *Excess Scan Policy* field
controls what happens when the scanned quantity exceeds the demand:

* *Allow*: the extra quantity is added with an information message;
* *Warn and Require Confirmation* (default): the operator must press
  *Force* to add the extra quantity;
* *Forbid*: the scan is rejected.
