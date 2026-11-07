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

Open Food Facts' software marks a product with a flag when something looks wrong: a figure that does not fit the others, a missing field, an odd value. Each flag has a weight: error, warning or information. This page counts the flags that are open on the products PackSense holds, day by day.

## How to read it

- Flags are counted, not products. A product can carry many flags, and on average a product here carries about nine.
- That number is steady. When the total goes up, it is mostly because more products are held, not because the data got worse.
- Two kinds of flag make up most of the total (about four in five), so each kind is drawn on its own line. Otherwise they would hide everything else.
- Only whole days are shown. OFF publishes its daily file from about 12:00 IST to 12:00 IST, so the newest day on the calendar is always incomplete and is left out.

## Across all of Open Food Facts

The charts above describe the products PackSense holds. The charts in this part describe the whole of Open Food Facts. They come from the public copy of its database that is saved every week, so each point is one week, not one day.

- The first three charts count products: how many are listed, how many were added or removed, and how many were edited between two weekly copies.
- A flag counts as ended when it left a product that is still listed and no other flag of the same kind took its place. It does not say who fixed anything, or that the data became right.
- Open flags are counted, not products. Only the forty largest kinds of flag are named; the smaller kinds are added together.
- A very busy week can come from one large automated change. The files do not say who edited.

## What this page can and cannot tell you

- The charts at the top describe the data PackSense holds. The part called "Across all of Open Food Facts" describes the whole database, week by week.
- A flag that disappears may mean a fix, a rename of the flag, or the product being removed. The page does not claim the first.
- The earliest days are thin: collecting started on 30 September 2026.
