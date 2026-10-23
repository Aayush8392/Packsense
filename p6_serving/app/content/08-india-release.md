---
slug: india-release
title: India data release
section: Get the data
order: 8
question: Can I download the India data, and what is in it?
built_from: The monthly release on Hugging Face (huggingface.co/datasets/Anonymous8392/packsense-india)
design_notes:
  - "A download button and the first rows of the file sit here."
  - "The product count and date below are the first release (22 October 2026); the app should read the live numbers from the release's manifest when it is built."
---

# Download India's food data, free.

Once a month we publish a clean list of the Indian products we hold, as a spreadsheet file anyone can download. The first release, on 22 October 2026, has 24,932 products. It is on the Hugging Face website, a free home for datasets.

Each row is one product: barcode, name, brand, pack size, categories, labels, and the nutrition figures per 100 g. A short guide in plain words explains every column, and a change list says what was added, removed or changed since the last release.

## What is in it, and what is not

- Not included: photos, ingredient text, anything about who edited a product, and any name or brand that looks like a phone number.
- Not everything is food. Open Food Facts also holds cosmetics, medicines and pet food, and we have not filtered them out.
- A flag means "worth a look", not "wrong".
- A product marked "unverified" has not been checked against OFF yet. It does not mean the product does not exist.
- A few values may look like a person's name typed in as a product. We cannot tell these from real products.

**Licence.** You may use it, including commercially, if you credit Open Food Facts and share anything you build from it under the same licence (the Open Database License).
