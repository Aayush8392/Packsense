# p6_serving/app: the public app and its page texts

The public front end is a fully custom static app (Vite, React and TypeScript, context amendment A85). It is built in eight slices; the owner moved it ahead of Phase E on 2026-10-28.
**Slice 1 (this folder):** the design spec (`DESIGN_SPEC.md`), the scaffold, the colour and type tokens (`src/tokens.css`, light and dark), the shell (six tabs, a second-level row, a breadcrumb, a mobile
menu, a footer with the Open Food Facts credit and the real build time), the router (every view has its own address; `404.html` is a copy of `index.html` so a deep link works on GitHub Pages) and the
content loader, which turns each file in `content/` into a page at build time. Every routed page currently shows its text only; the data parts arrive in slices 2 to 7. Evidence stays live until slice 8.

Run it from this folder (Node 24): `npm ci --ignore-scripts`, then `npm run dev` (development), `npm test` (types are checked by `npm run typecheck`), `npm run lint` and `npm run build`.
Packages are pinned exactly and were chosen at least two weeks after their release (`npm install --before=<date>`); `undici` is overridden to a patched release because `jsdom` (tests only) pulled in a vulnerable one.
**Data (slice 2 on).** The app reads the published CSV files from its own `data/` folder (`site_status.csv`, `change_daily.csv`, `pipeline_health.csv`; more in later slices) and never shows a number it did not read. For local
development put the real files in `p6_serving/app/public/data/` (git ignores that folder): run `HF_SITE_READ_TOKEN=... python p6_serving/fetch_site_data.py Anonymous8392/packsense-site-data <folder>` and copy the CSVs there. The
Pages workflow copies the same files next to the built app at cutover (slice 8). `src/data/fixtures/` holds real rows of the same files for the tests; `src/data/jobs.json` lists the pipeline jobs and their cadence (a test in
`p6_serving/tests/test_app_jobs.py` keeps it in step with the collector).

Page 06 (India today) and page 11 (Ask a question) have no address of their own: they become a block inside Daily changes and a panel inside Look up, and their files stay here until those slices.

## The page texts

This folder also holds the
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
- The page texts were rewritten in the impersonal voice on 2026-10-24 (a test enforces it). The slugs `how-we-differ` and `how-we-work` and the `design_notes` still say "we"; the titles do not.
- Page 10 must say the number is typed (camera scanning is not offered).
- Page 01 (Home): the owner wants to discuss showing more important numbers than the three listed.
- Page 10 (barcode lookup) carries the signal wording decided on 2026-10-24 (the first draft's words were replaced) and the lookup rule for the product-card files.

Data these pages read, all already published by the daily jobs: `brand_scorecard.csv`, `quality_daily.csv`, `change_daily.csv`, `pipeline_health.csv`, `site_status.csv` on the site and `cards/` for the lookup;
the one-off `p6_serving/showcase/showcase.json` for page 07; the India release on Hugging Face for page 08.
