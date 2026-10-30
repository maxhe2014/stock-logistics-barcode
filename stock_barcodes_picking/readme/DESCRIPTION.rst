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
