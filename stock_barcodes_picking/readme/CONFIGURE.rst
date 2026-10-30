Barcode timing
==============

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
