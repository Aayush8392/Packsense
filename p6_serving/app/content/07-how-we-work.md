---
slug: how-we-work
title: How we work
section: How it works
order: 7
question: How does raw data become the tables you see?
built_from: Four real products shown at each step, personal parts replaced (p6_serving/showcase/showcase.json)
design_notes:
  - "A drawn flow of the three steps sits at the top."
  - "Presentation decided 2026-10-24: bronze and silver as key-and-value lists (the raw record is a long nested list, the silver row is one row of 81 columns turned on its side, hidden columns greyed and marked 'hidden on purpose'); gold as real tables with their columns across (history, flag spans, nutrition sets, rule verdicts, the product card, and one row each from the brand, daily change and daily quality tables)."
  - "Also a short 'same field, three steps' comparison (name, pack size, categories, nutrition: raw, silver, gold). It needs no change to the data file."
  - "The four products are in the showcase file: an ordinary packaged food (Kinder Surprise), one with several OFF flags (Farmer Salat), one with a long edit history (Fairlife chocolate milk) and an Indian one (Parle Monaco). Volunteers' usernames are stand-ins (contributor-A and so on); some entries are app accounts shown the same way as people."
---

# From a raw file to a table you can read.

This page follows real products through the three steps every record goes through. Everything shown is real data. Where something private was removed, the page says so and shows the gap.

**Step 1: the raw copy (we call it bronze).** Every morning we download Open Food Facts' newest file and store it exactly as it arrived, untouched. It is messy: the file uses about 6,000 differently named fields, which fall into roughly 376 families, and it includes the usernames of the volunteers who edited each product. *Shown here: one real product's raw record, with usernames and images replaced by a marker.*

**Step 2: the cleaned copy (silver).** We keep a fixed set of 81 columns. Mistakes are caught here: tags that do not look like tags are dropped and counted, web addresses and email-like text are removed, and volunteers' usernames are turned into scrambled codes that never leave the private side. *Shown here: the same product as one cleaned row, with the hidden columns marked "hidden on purpose".*

**Step 3: the tables for answers (gold).** From the cleaned copy we build the tables this site shows: each product's history, the flags it carried and when, its nutrition by source, and the daily summaries. *Shown here: the same product's history and flags, then one row from each summary table.*

## What this page can and cannot tell you

- The products are a handful picked to show the steps. They are not a search over the whole copy.
- Removing private parts is checked and measured, but we state it as a measured limit, not as a guarantee.
- The raw copy is never shown whole. It holds volunteers' usernames, which Open Food Facts publishes but we do not republish.
