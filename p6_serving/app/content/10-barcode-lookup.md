---
slug: barcode-lookup
title: Look up a barcode
section: Look up
order: 10
status: later
question: What does PackSense know about this product?
built_from: The product cards (cards/<prefix>.csv on this site; mart_product_card)
lookup_rule: "Take the first 3 digits of the barcode; while that prefix is in cards/splits.json, take one more digit; fetch cards/<prefix>.csv; a missing file means 'not in our copy'. Barcode shapes (EAN-13, 12-digit UPC, EAN-8, GTIN-14, a missing leading zero) are checked with the check digit and variants are tried."
signal_labels:
  several_flagged:
    label: "Several things flagged"
    line: "Flagged by Open Food Facts' own checks or by PackSense's 11 arithmetic checks. A flag means worth a look, not wrong."
  one_flagged:
    label: "One thing flagged"
    line: "Flagged by Open Food Facts' own checks or by PackSense's 11 arithmetic checks. A flag means worth a look, not wrong."
  none_flagged:
    label: "Nothing flagged"
    line: "Open Food Facts' own checks and PackSense's 11 arithmetic checks found nothing. This does not mean the entry is correct."
  not_enough_data:
    label: "Not enough data to check"
    line: "The checks could not be run because there is no nutrition table to check."
design_notes:
  - "Wording decided 2026-10-24 (replaces the first draft's 'looks consistent', 'some things to check', 'several things flagged'). Only OFF's error and bug flags and our failed checks count toward the signal; warnings and information flags are shown but not counted. The data holds neutral codes (several_flagged, one_flagged, none_flagged, not_enough_data); the words and colours belong to the app."
  - "The card also shows existence_status (products OFF has removed or moved stay in the data) and the OFF link built from the barcode. A removed or moved product says so instead of showing the signal as normal."
---

# What does PackSense know about this product?

Type the number printed under a barcode. If the product is in this copy, you see a short card:

- A signal, in four words: **Several things flagged**, **One thing flagged**, **Nothing flagged** or **Not enough data to check**, with a line under it that says what a flag means.
- How many warnings Open Food Facts has recorded for it, and how serious they are.
- How many of PackSense's own arithmetic checks it fails.
- How many of seven key fields are filled in.
- How many versions have been kept, when it was last edited, and the first version held.
- Whether it is in the India slice.
- A button that opens the product on Open Food Facts.

The card shows no photos and no ingredient text. If the number is not found, it says "not in this copy". That does not mean the product is not on OFF.

*The signal is a summary of the facts under it. It never says a product is right or wrong.*
