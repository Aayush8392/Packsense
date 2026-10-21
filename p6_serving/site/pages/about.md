---
title: About this data
---

## Source and licence

Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/). This site describes our own copy of that data at the stated build time, not Open Food Facts itself. It shows no product images and no contributor names.

## What this is

A pipeline captures the daily change file of Open Food Facts, cleans it, keeps every version of every product, and measures quality from it. This site shows aggregates only.

## What it is not

- It is not the current state of Open Food Facts. A product can be up to a day behind its live page, and some products have changed twice between two versions we hold.
- It does not say a value is correct. Open Food Facts is crowd-edited; we report what is consistent with its rules and what its own checks flag.
- It does not cover all of Open Food Facts. We hold products edited since 30 September 2026, plus a one-time snapshot of India products.
- Small counts (1 to 4) are hidden. A hidden cell can sometimes be recovered from a total next to it, so this is not formal disclosure control.
- Brand pages show completeness for brands with at least 30 products. They do not show per-brand error counts.

## Method

Coverage and flags are counted from silver and gold tables built with documented rules. Data is rebuilt daily and published after a licence check that refuses an export containing images, personal fields or a missing attribution. The code is at https://github.com/Aayush8392/Packsense.
