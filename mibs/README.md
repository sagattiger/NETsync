# MIBs

Vendor MIB files, one folder per vendor (same idea as Observium's `mibs/` tree):

```
mibs/
  rfc/        standard MIBs (IF-MIB, HOST-RESOURCES-MIB, ENTITY-MIB, ...)
  cisco/
  mikrotik/
  fortinet/
  juniper/
  ...
```

How NETsync uses them:

- **Polling does not parse MIBs.** Modules use numeric OIDs, so polling is fast and a broken
  MIB file can never break it.
- MIBs are **compiled once** (with `pysmi`) into `mibs/compiled/` (a JSON OID → name index). That
  index powers OID names in the UI (SNMP browser / walk tool), SNMP trap translation and
  custom checks created from the UI. *(planned, milestone 2)*
- Some vendors don't allow their MIBs to be redistributed. Only freely redistributable MIBs
  are committed to this repo; drop any others into the matching vendor folder and they will
  be picked up the next time the MIBs are compiled.
