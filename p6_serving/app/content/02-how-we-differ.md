---
slug: how-we-differ
title: How PackSense differs from Open Food Facts
section: How it works
order: 2
question: What does PackSense add that Open Food Facts does not?
built_from: Hand-written; a few measured facts
checked_claims:
  - "more than four million products"
  - "more than 100,000 contributors"
  - "photos of the packs"
design_notes:
  - "The three claims in checked_claims were checked on 2026-10-24 against Open Food Facts's own pages (world.openfoodfacts.org/discover): '4 000 000+ products from 150 countries', '100.000+ contributors like you', and contributors can upload pictures of products and labels. The page gives no 'as of' date, so the wording stays 'more than' and is re-checked when the page is next edited. The first draft said 'thousands of volunteers', which was true but far too low."
  - "The comparison table is kept as a short summary of the page for readers who do not read the whole page. The old 'Live?' column was dropped by the owner."
---

# How PackSense differs from Open Food Facts

PackSense does not replace Open Food Facts (OFF). It depends on OFF. OFF is where the products are written and fixed. PackSense is a second pair of eyes that keeps a record and reports what it sees.

**What OFF is good at.** OFF has more than four million products, more than 100,000 contributors, and photos of the packs. It already checks its own data: its software flags a product when, for example, the energy figure does not fit the nutrients. In a sample of 81,951 recently changed products from 13 days in October 2026, about 31% carried at least one OFF nutrition flag. PackSense was not built as a rival to that.

**What PackSense adds.** The table below is the short version.

| Question | What OFF gives you | What PackSense adds |
|---|---|---|
| How did this product look last week? | The latest version | Every daily version it saw, kept |
| How much is edited each day? | Not summarised | Daily counts of edits by kind (name, nutrition, ingredients and so on) |
| Is the data improving? | Not summarised | Open flags per day, grouped by kind |
| Which brands fill in their products well? | You can browse a brand | A ranking of brands with 30 or more products, by how many key fields are filled |
| Was a missing product deleted or moved? | The daily files carry no deletion marker | Each missing product is checked against OFF's public data and the answer is recorded: gone, moved to another OFF database, or still there |
| What changed in India today? | You can filter, but there is no daily list | A daily summary for India, with a real example |
| Does the arithmetic hold? | OFF's own checks | PackSense's own 11 checks, run on each source of nutrition data separately |
| Where do two sources of nutrition data disagree? | No such check, as of October 2026 | A detector for this |

## The 11 checks

These are simple sums that Open Food Facts already runs on its own data. PackSense copied them as they are, with the same allowed margins. Each one is run on every source of nutrition data separately, per 100 g or 100 ml.

1. **Calories bigger than kilojoules.** A kilocalorie is smaller than a kilojoule (1 kcal is 4.184 kJ), so the kcal number should never be larger than the kJ number.
2. **Calories and kilojoules swapped.** The two numbers look entered in the wrong boxes.
3. **Calories and kilojoules disagree.** The kJ figure should be roughly 4.2 times the kcal figure. It is flagged when it falls outside the range of 3.7 to 4.7 times, with a margin of 2.
4. **Energy in kJ does not match the nutrients.** The energy is added up from fat, carbohydrates, protein and the rest. A gap over 30% (plus 5) is an error, and over 15% (plus 5) is a warning.
5. **Energy in kcal does not match the nutrients.** The same check, in kcal.
6. **Energy over 3,911 kJ in 100 g.** For comparison, pure fat holds about 3,700 kJ.
7. **Salt and sodium disagree.** Salt is about 2.5 times sodium. A gap over 0.1 g is flagged.
8. **Sugars and starch bigger than carbohydrates.** The parts cannot be larger than the whole.
9. **Saturated fat bigger than total fat.** The same reasoning.
10. **Any nutrient over 105 g in 100 g.** 100 g of food cannot hold more than 100 g. Open Food Facts allows 105 g because 100 ml of some drinks weighs more than 100 g.
11. **Fat, carbohydrates, protein and salt together over 105 g.**

A check is skipped when a number it needs is missing. That is why many products say "Not enough data to check".

**What PackSense does not claim.** It cannot tell you whether a number on a pack is true. It tells you whether OFF's entry agrees with itself and with OFF's own rules. It does not edit OFF. Any fix it ever suggests is for a person to review and make.

**This copy is not OFF.** For India, PackSense holds almost every product OFF had in mid-October, plus everything edited since. For other countries it holds only the products edited since 30 September 2026. A product missing here may still be on OFF.
