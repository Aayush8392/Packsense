---
license: odbl
pretty_name: PackSense India product catalogue
language: [en]
tags: [open-food-facts, food, nutrition, india, barcodes]
---

# PackSense India product catalogue (release 2026-10-22)

Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/). This release describes our own copy of the data at the stated build time, not Open Food Facts itself; the individual contents are under the Database Contents License and product images (not included) have their own licences.

## What is this?

A list of 24,932 packaged products sold in India, with their barcode, name, brand, pack size, nutrition values and quality flags. It is a cleaned copy of what the Open Food Facts community has entered, taken at the time stated below. It is meant for people who build apps or analyses on top of product data, and for anyone who wants to see how complete the data is.

Built at 2026-10-22T12:30:20 UTC. One file: `india_products.csv` (a plain CSV, one row per product, sorted by barcode).

## What to know before you use it

- **Anyone can edit Open Food Facts**, so values can be missing, wrong or out of date. Many rows have only a barcode and a name. Nothing here is checked against the real pack.
- **Not everything is food.** Open Food Facts users also add cosmetics, medicines, electronics and pet food, and we do not remove them. Some rows are completely empty.
- **A product may have changed** on Open Food Facts since the build time. We take a daily copy and can miss edits made between two copies.
- **Lists are joined by `|`** (for example several categories in one cell). An empty cell means we have no value.
- **Quality flags** (`open_error_flags`, `open_warning_flags`, `open_info_flags`) are counts of the warnings that Open Food Facts' own checks raised and that were still open at our last look. A flag means the data looks inconsistent. It does not mean a value is wrong, and no flag does not mean it is right.
- **`existence_status`** says what our last check found: `present_in_snapshot` (listed in a recent Open Food Facts snapshot), `confirmed_exists` (their API confirmed it), `unverified` (not checked yet; do not read it as 'exists'), `invalid_code` or `unconfirmed`. Products that Open Food Facts told us are gone, or moved to another of its databases, are left out.
- **`last_modified_t`** is the time of the newest edit we saw, as a Unix timestamp (seconds since 1970).

## What is not in it

No pictures or picture links. No ingredient text. No names or codes of the people who edited a product. Free text (name, brand, tags) was cleaned: emails, links, social handles and Indian ID numbers were removed, known contributor usernames of eight or more letters were replaced by `‹user›`, and a name or brand that looks like an Indian mobile number was left empty. This lowers the chance that personal data remains. It cannot guarantee it: for example, a person's own name typed as a product name cannot be told apart from a real product name. If you find personal data in the file, please tell us so we can remove it.

## The columns

The table shows how many rows have a value in each column.

| column | rows filled | share |
|---|---|---|
| `code` | 24,932 | 100.0% |
| `product_name` | 21,557 | 86.5% |
| `brands` | 16,778 | 67.3% |
| `quantity_amount` | 8,471 | 34.0% |
| `quantity_unit` | 8,471 | 34.0% |
| `product_quantity` | 10,450 | 41.9% |
| `product_quantity_unit` | 9,171 | 36.8% |
| `serving_amount` | 7,809 | 31.3% |
| `serving_unit` | 7,809 | 31.3% |
| `pnns_groups_1` | 24,267 | 97.3% |
| `pnns_groups_2` | 24,267 | 97.3% |
| `nutrition_format` | 24,932 | 100.0% |
| `nutrition_per` | 8,101 | 32.5% |
| `nutrition_preparation` | 11,359 | 45.6% |
| `energy_kj` | 10,759 | 43.2% |
| `energy_kcal` | 10,736 | 43.1% |
| `fat` | 10,659 | 42.8% |
| `saturated_fat` | 9,082 | 36.4% |
| `carbohydrates` | 10,716 | 43.0% |
| `sugars` | 9,668 | 38.8% |
| `fiber` | 5,669 | 22.7% |
| `proteins` | 10,688 | 42.9% |
| `salt` | 9,177 | 36.8% |
| `sodium` | 9,177 | 36.8% |
| `nutriscore_grade` | 24,267 | 97.3% |
| `nova_group` | 6,921 | 27.8% |
| `environmental_score_grade` | 20,148 | 80.8% |
| `categories_tags` | 11,944 | 47.9% |
| `labels_tags` | 7,120 | 28.6% |
| `allergens_tags` | 4,412 | 17.7% |
| `traces_tags` | 551 | 2.2% |
| `open_error_flags` | 24,932 | 100.0% |
| `open_warning_flags` | 24,932 | 100.0% |
| `open_info_flags` | 24,932 | 100.0% |
| `existence_status` | 24,932 | 100.0% |
| `last_modified_t` | 24,932 | 100.0% |

11,359 products (45.6%) have a nutrition table, 5,303 (21.3%) have a Nutri-Score grade, and 754 have at least one open error-level flag.

## Licence

The database is available under the Open Database License (ODbL 1.0): you may use and share it, you must credit Open Food Facts, and if you share a changed version of the database you must keep it under the same licence. The individual entries are under the Database Contents License. See https://opendatacommons.org/licenses/odbl/1-0/ and https://openfoodfacts.org/terms-of-use.

## How it was made

Built by the PackSense project from its daily copy of Open Food Facts. The numbers in this card are computed from the file itself. What the privacy cleaning did in this release: {"columns_dropped": 0, "names_replaced": 35, "ordinary_names_left_alone": 40, "patterns_removed": 0, "phone_shaped_blanked": 7, "rows": 24932}.
