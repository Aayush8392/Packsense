---
slug: quality-over-time
title: Data quality over time
section: Explore the data
order: 4
question: Is the data getting better or worse?
built_from: Daily quality table
design_notes:
  - "Charts sit here: one line chart per kind of flag, with a separate view for errors only."
  - "Later, an 'AI reading of this table' block is added under the charts."
---

# Is the data getting better or worse?

Open Food Facts' software marks a product with a flag when something looks wrong: a figure that does not fit the others, a missing field, an odd value. Each flag has a weight: error, warning or information. This page counts the flags that are open on the products we hold, day by day.

## How to read it

- We count flags, not products. A product can carry many flags, and on average our products carry about nine.
- That number is steady. When the total goes up, it is mostly because we hold more products, not because the data got worse.
- Two kinds of flag make up most of the total (about four in five), so we draw each kind on its own line. Otherwise they would hide everything else.
- We show only whole days. OFF publishes its daily file from about 06:30 UTC to 06:30 UTC, so the newest day on the calendar is always incomplete and is left out.

## What this page can and cannot tell you

- It describes the data we hold, not all of Open Food Facts.
- A flag that disappears may mean a fix, a rename of the flag, or the product being removed. We do not claim the first.
- The earliest days are thin: we started collecting on 30 September 2026.
