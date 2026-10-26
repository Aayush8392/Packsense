# Labelling cards (Phase D, item 16)

Code for the unaided labelling gate of design 7.2: the human decides what the arithmetic rules cannot, and the gate checks that the labeller agrees with themself a week apart.
The guide the labeller follows is a Claude Doc (not in this repo). Labels and the cards themselves stay on `D:` and are never committed; only the counts of the result are published.

| File | What it does |
|---|---|
| `cards_lib.py` | Pure functions: which OFF flags are in scope, the plain-words flag text, the photo links, the card, the deterministic selection |
| `select_cards.py` | Admin, read-only on production: picks 20 practice cards (2 sets of 10, at most 4 per flag family) and the 30 cards of the real test (at most 6 per family), writes Label Studio task files outside the repo |
| `project_config.xml` | The Label Studio screen: nutrition photo, the card (native Label Studio tables, so both themes work), the three labels, an optional reason code, a note |
| `create_project.py` | Creates a project in the local Label Studio and imports a task file; `--shuffle-seed` gives round 2 a new order |

**Scope.** Open error and warning flags of these families: `value-very-high/low-for-category-<nutrient>`, `value-under-0-01-g-salt`, `value-under-0-001-g-salt`, `3-or-more-values-are-identical`.
Products where any of our 11 rules is violated, and products OFF removed or moved, are left out. Measured 2026-10-25: 15,211 products carry such a flag, 1,734 of them violate a rule.

**Selection.** Candidates are ordered by the md5 of the barcode (no randomness). A candidate is kept when OFF's product API shows a selected nutrition photo (3 s between calls, answers cached) and its flag family has room under the cap.
Practice and test sets never share a product. The photos are loaded from OFF in the browser and are not stored.
