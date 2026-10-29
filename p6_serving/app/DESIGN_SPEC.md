# PackSense app: design spec

The look of the public app. Source: the Stitch exports kept (locally) in `designs/`, judged for layout, colour, type and spacing only. No Stitch wording is used anywhere: the live text of every page
is the hand-written text in `content/`. Where this spec and an export disagree, this spec wins.

## Principles
- Editorial, calm, flat. Warm paper background, hairline rules, no drop shadows (one soft shadow is allowed for popovers), no gradients, no green-versus-red signals.
- Quality is described as "flagged" or "consistent", never "correct".
- Every claim on a page is computed from published data or written in `content/`. A figure that is a lower bound says "at least".

## Sizing (no hard-coded pixel layouts)
- Type and spacing are in `rem`, so the visitor's browser font size is respected. 1 px hairlines stay `px`.
- Widths use `%`, `fr`, `min()`, `max()` and `clamp()`. Headlines use `clamp()`. Every page has the same width (85rem), and body text runs the full width of it, justified from 40rem up.
- Components adapt with container queries; media queries are used only for the few page-level layout breakpoints (48rem for the menu, 64rem for the wide layouts).
- Smallest text is `0.75rem`. Tap targets are at least `2.75rem`. Font sizes are never percentages.
- Tables are fluid and turn into cards below a container breakpoint (about 64rem). Scroll panes are used only when a column set cannot be reduced.
- Charts are our own SVG and keep their aspect ratio (no stretched strokes). One chart never mixes two scales; each chart has a "show as table" fallback.

## Theme
- One dark mechanism: the system setting (`prefers-color-scheme`). No toggle. The tokens are CSS custom properties on `:root`; dark values are set once in the media query.
- Light values come from page 02's `DESIGN.md`; dark values from the same page's dark block.
- Contrast: body text at least 4.5:1 against its background in both themes (`src/tokens.test.ts` checks every text pair in both themes).

## Colour tokens
| Token | Light | Dark |
|---|---|---|
| `--bg` | `#faf9f7` | `#141718` |
| `--fg` | `#1a1c1b` | `#f1f1ef` |
| `--fg-muted` | `#43474e` | `#b9c7df` |
| `--primary` | `#09284c` | `#aec8f4` |
| `--secondary` | `#515f74` | `#b9c7df` |
| `--border` | `#c4c6cf` | `#43474e` |
| `--card` | `#ffffff` | `#1c1f21` |
| `--soft` | `#f4f3f1` | `#23272a` |
| `--raised` | `#efeeec` | `#2c3135` |
| `--on-primary` | `#ffffff` | `#141718` |
| `--advisory-bg` / `--advisory-fg` | `#fef3c7` / `#92400e` | `#3a2a08` / `#fcd34d` |

## Type
- Headings: Newsreader (500; 600 for the smallest). Text and UI: Public Sans. Both are self-hosted from npm packages, so a visit makes no request to a font service.
- Scale (rem): display `clamp(2rem, 1.5rem + 2vw, 2.75rem)`, headline-lg `clamp(1.625rem, 1.3rem + 1.2vw, 2rem)`, headline-md 1.5, headline-sm 1.25, title 1.125, body-lg 1.0625, body 0.9375, small 0.8125, label 0.75.
- Numbers use `font-variant-numeric: tabular-nums lining-nums`.

## Shape and rules
- Radius 0.25rem for inputs, buttons, blocks; 0.1875rem for tags. Hairline borders 1px `--border`. Major section breaks may use a double rule.
- Focus: a 2px outline in `--primary` with offset; never removed.

## Navigation
- Six tabs: Home, Explore the data, How it works, Get the data, Look up, About.
- A second-level row exists only for Explore (Brands, Data quality over time, Daily changes), How it works (How PackSense works, How PackSense differs, Pipeline health) and Look up.
- A breadcrumb shows where the visitor is. On small screens the tabs move into a drawer: the button has `aria-expanded` and `aria-controls`, the drawer closes on Escape, and focus returns to the button.
- Every view has its own address. The chosen view, market and barcode are kept in the address.

## Accessibility
- Results, errors and loading states are announced (`role="status"` or `aria-live`). State is never shown by colour alone: words and glyphs, plus different markers and line styles in charts.
- A skip link comes first. Landmarks: header, nav, main, footer. Inputs have labels; the barcode field uses a numeric keyboard.

## Every page carries
- The Open Food Facts credit and the real build time (written at build, not a guess).
- A "what this page can and cannot tell you" note on the table pages.
- No contact or takedown route and no "who made this" section.

## Page layouts (what each Stitch export contains; the live text is ours)
Common frame, built in slice 1: sticky header (brand, tabs, a "Look up barcode" button), a second-level row for Explore, How it works and Look up, a breadcrumb, a page title block, a footer with the
credit and the build time. Explore pages also share: a market switch (All markets | India, a radio group), a code-computed headline box, a chart card with a "show as table" button, a "How to read it" panel, a
"What this page can and cannot tell you" panel, and an empty "AI reading of this table" slot that stays hidden until the AI layer exists.
- **Home (built as slots in slice 1b, live numbers in slice 2):** hero; barcode box; three headline numbers (label above, number below); a "Right now" strip of five facts; "What you can do" as a list of links; an aside with what the site does not do and the small print.
- **Article pages (How PackSense differs, About; built):** title block with the question, framed tables, sections divided by a rule.
- **Brands (slice 4):** market switch; a code-computed headline sentence; a histogram of how many of the 7 things brands fill, which filters the table; a brand search box; a ranked table with paging (cards below the container breakpoint); the can-and-cannot panel.
- **Data quality over time (slice 3):** market switch; a headline box (two figures and a date range, computed, never "better" or "worse"); two plain charts, flags per product and products held; small multiples by severity with different markers and line styles; a table of the most common flag families; "How to read it"; the can-and-cannot panel.
- **Daily changes (slice 3):** market switch; three headline figures; one chart area with a view switch (products edited vs new, work by kind); a table of kinds (never summed); a "Today in India" block (counts, kinds, recent days, one labelled example product); can-and-cannot panel.
- **How PackSense works (slice 7):** a three-step flow (raw, cleaned, tables for answers); a four-product switcher; "same field, three steps"; a searchable raw viewer; silver as a vertical list with "hidden on purpose" rows; gold tables as cards on a phone and fluid tables on desktop.
- **The India release (slice 7):** a download card with the release tag and size; a column dictionary beside a sample preview (cards on a phone); five limits; a copyable credit line; steps for opening the file without breaking barcodes (to be tested in Excel and Sheets first); a versions table; labelled states for loading, unreadable manifest and not yet published.
- **Pipeline health (slice 5):** a status line; a jobs table (cadence-aware verdicts, cards on a phone); a runtime chart with direct labels and a table view; products held over time; outside services with the expected 403 explained; the can-and-cannot panel.
- **Look up (slice 6):** a barcode tool and a question tool side by side on desktop, a switch on a phone; result cards for each state (found, not in our copy, bad check digit, error); the question bot with example questions and "start again". Results and errors are announced to screen readers.

## Things the build never copies from a design
Demo toggles and state-preview bars, fixed-width device wrappers, the Tailwind CDN, class-based dark switches, scroll panes with hard minimum widths, and any wording or claim that is not in `content/` or computed from published data.
