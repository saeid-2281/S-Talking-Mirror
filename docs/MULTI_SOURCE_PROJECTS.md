# Multi-Source Projects

S Talking projects can now model multiple source files. A project source records file path, type, worksheet, enabled state, import order, detected CSV encoding/delimiter, column mapping, source hash, row counts, and import status.

Supported source files:

- CSV
- TSV
- XLSX
- XLSM

Legacy `.xls` files are reported as unsupported and should be converted to `.xlsx`.

Merged queue order is source import order, then worksheet order, then physical row order. Jobs keep source provenance: source ID, source display name, sheet name, and physical source row. Filename collisions across enabled sources are blocking and must be resolved explicitly.

Source files are never modified during import.
