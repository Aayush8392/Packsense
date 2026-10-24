# p6_serving/app: the public site's content (the app itself is built later)

The public front end is a fully custom static app (Vite and React, context amendment A85), built after the AI layer exists (Phases C to E). This folder holds only what is already decided: the
**text of every page**, copied on 2026-10-24 from the owner's approved Claude Doc "PackSense site: page list and first drafts".

`content/NN-slug.md`: one file per page, 12 in all. Each starts with front matter (`slug`, `title`, `section`, `order`, `question`, `built_from`, optional `status: later`, `design_notes`) and then the
hand-written text, in plain language for any visitor. The menu follows the Doc: Home; Explore the data (Brands, Data quality over time, Daily changes, India today); How it works (How we work,
How we differ from Open Food Facts, Pipeline health); Get the data (the India release); Look up (barcode lookup and Ask a question, both `status: later`); About.

Rules that hold for this text (decisions in the context file, A84 to A90):
- Hand-written explainers are PERMANENT. The AI layer later ADDS an "AI reading of this table" block under a table page (describe-only) and never replaces them.
- Every page carries the Open Food Facts credit, the real build time and a phone-friendly layout; the table pages carry a "what this page can and cannot tell you" note.
- Words about quality are "flagged" and "consistent"; never "correct". There is no contact or takedown route and no "who made this" section.
- `design_notes` in the front matter are notes for the designer (what chart or table sits where, which published table feeds it); they are not page text.

**Open before the site is released:**
- Page 02's three claims in `checked_claims` were checked on 2026-10-24 against Open Food Facts's own pages (more than four million products, more than 100,000 contributors, photos of the packs).
  Open Food Facts gives no 'as of' date, so re-check them whenever the page is next edited.
- The page texts use "we" and "our copy". The question bot speaks impersonally ("PackSense", "the site"), so the pages are rewritten the same way when the app is built (owner's decision, 2026-10-24).
- Page 10 must say the number is typed (camera scanning is not offered).
- Page 01 (Home): the owner wants to discuss showing more important numbers than the three listed.
- Page 10 (barcode lookup) carries the signal wording decided on 2026-10-24 (the first draft's words were replaced) and the lookup rule for the product-card files.

Data these pages read, all already published by the daily jobs: `brand_scorecard.csv`, `quality_daily.csv`, `change_daily.csv`, `pipeline_health.csv`, `site_status.csv` on the site and `cards/` for the lookup;
the one-off `p6_serving/showcase/showcase.json` for page 07; the India release on Hugging Face for page 08.
