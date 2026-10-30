==================
Stock Barcodes MRP
==================

This module provides a touch-friendly barcode scanning screen for
manufacturing orders. Operators scan the manufacturing order, the
source location, component barcodes and serial/lot numbers, then the
finished product serial number; the screen keeps every step in sync and
validates the scanned values immediately.

Highlights:

* scan the MO, source location, components and finished product serial;
* scan serial numbers straight away, without selecting the component
  first;
* warn about duplicate or unusable serial numbers at scan time;
* trace material lots consumed by a finished lot, and finished lots
  produced from a material lot.

Usage
-----

Barcode scanning
~~~~~~~~~~~~~~~~

#. Open the manufacturing order and press *Scan barcodes*.
#. Scan the manufacturing order barcode when the screen asks for it.
#. Scan the source location, then the components and their serial/lot
   numbers.
#. Scan the finished product serial number.
#. Press *Finish* to validate the manufacturing order.

Traceability
~~~~~~~~~~~~

On a serial/lot form, the smart buttons open the material lots consumed
to produce it and the finished lots produced from it.

Credits
-------

Authors
~~~~~~~

* OpenViking

License
~~~~~~~

AGPL-3.0 or later.
