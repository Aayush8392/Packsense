"""Silver logic as plain Python (no Spark), so it can be unit-tested against real records.

contract.py   loads and validates contracts/silver.yml (the allowlist)
personal.py   normalising, HMAC, scrubbing and the known-identity checks
transform.py  one raw bronze record -> one silver row, or one quarantine row with a coded reason

The Databricks notebook applies transform.process to every bronze row.
"""
