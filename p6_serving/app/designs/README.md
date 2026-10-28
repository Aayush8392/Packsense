# p6_serving/app/designs: Stitch exports (look references only)

Each screen the owner designs in Stitch is exported as a zip and kept here, named `NN_screen_variant.zip` (for example `01_home_desktop-mobile.zip`), with the extracted folder beside it.
The zips stay local (`.gitignore`); the extracted HTML and the design tokens are committed.

A design is a reference for the look only: layout, colours, type, spacing, components. Its wording is never used. The live text of every page is the hand-written text in `../content/`.
