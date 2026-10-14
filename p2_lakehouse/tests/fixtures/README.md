# Fixtures for the silver tests

`bronze_records.jsonl`: 20 real records from PackSense's bronze table (Open Food Facts daily delta files, 13-14 Oct 2026),
one per line as `{"case": ..., "raw_json": ...}`. Each case covers a situation the silver logic must handle (a normal
product, no nutrition, per 100 ml, a non-numeric barcode, an email in the ingredients, ...).

Source and licence: Open Food Facts contributors, ODbL (https://opendatacommons.org/licenses/odbl/1-0/).

What was changed before the file was committed (`p2_lakehouse/bootstrap/extract_fixtures.py` does it inside Databricks, so raw
contributor names never leave Databricks):
- every contributor identity became a stable placeholder (`user_0001`, ...), the same placeholder everywhere it appeared;
- `images` was removed;
- emails became `redacted<n>@example.org`; phone numbers in `customer_service*` and `producer*` became one fixed placeholder;
- the run proved that no original name survives in the text and returned only counts.

Everything else is the record exactly as it was sent. The placeholders are not real data; they replace personal data
(the project's publication policy: real slices, personal data removed). To regenerate: run the extraction script with an
admin token; the record selection is deterministic.
