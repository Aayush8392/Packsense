/**
 * What each column of the India file holds, in plain words. A draft for the owner to read and change: the file's data card lists the columns
 * with how many rows are filled but does not say what they mean. A column that is in the file but not here is shown with a dash, so a new
 * column can never be shown with a wrong meaning.
 */
export const COLUMN_GUIDE: Record<string, string> = {
  code: 'The barcode. Keep it as text: a spreadsheet that reads it as a number drops leading zeros.',
  product_name: 'What the product is called, as people typed it into Open Food Facts.',
  brands: 'The brand or brands on the pack.',
  quantity_amount: 'The pack size number, as printed (for example 700).',
  quantity_unit: 'The unit of the pack size (for example g or ml).',
  product_quantity: 'The pack size as one number, in grams or millilitres.',
  product_quantity_unit: 'Whether that number is in grams or millilitres.',
  serving_amount: 'How big one serving is, as printed.',
  serving_unit: 'The unit of one serving.',
  pnns_groups_1: 'The broad food group Open Food Facts gave the product (for example beverages).',
  pnns_groups_2: 'The more specific food group inside that one.',
  nutrition_format: 'How the nutrition figures were recorded: in the newer layout, in an older layout, or none at all.',
  nutrition_per: 'What the nutrition figures are counted for (for example per 100 g).',
  nutrition_preparation: 'Whether the figures are for the product as sold or as prepared.',
  energy_kj: 'Energy, in kilojoules, for the amount in the "nutrition_per" column.',
  energy_kcal: 'Energy, in kilocalories, for the same amount.',
  fat: 'Fat, in grams, for the same amount.',
  saturated_fat: 'Saturated fat, in grams.',
  carbohydrates: 'Carbohydrates, in grams.',
  sugars: 'Sugars, in grams.',
  fiber: 'Fibre, in grams.',
  proteins: 'Protein, in grams.',
  salt: 'Salt, in grams.',
  sodium: 'Sodium, in grams.',
  nutriscore_grade: 'The Nutri-Score letter, from a (best) to e (worst), or "unknown".',
  nova_group: 'How processed the food is, from 1 (not processed) to 4 (ultra-processed).',
  environmental_score_grade: 'The environmental score letter, from a (best) to e (worst), or "unknown".',
  categories_tags: 'The categories the product belongs to, joined by the | character.',
  labels_tags: 'Labels on the pack, such as organic, joined by |.',
  allergens_tags: 'Allergens the product contains, joined by |.',
  traces_tags: 'Allergens that may be present in traces, joined by |.',
  open_error_flags: 'How many of Open Food Facts\' own checks raised an error on this product and were still open at our last look.',
  open_warning_flags: 'The same, for warnings.',
  open_info_flags: 'The same, for information notes.',
  existence_status: 'What our last check found: seen in a recent Open Food Facts snapshot, confirmed to exist, or "unverified" (not checked yet, which does not mean it does not exist).',
  last_modified_t: 'When the newest edit we saw was made, as seconds since 1 January 1970.',
};

/** The columns the sample table shows, in order, with the heading each one gets. */
export const SAMPLE_COLUMNS: { key: string; label: string }[] = [
  { key: 'code', label: 'Barcode' },
  { key: 'product_name', label: 'Name' },
  { key: 'brands', label: 'Brand' },
  { key: 'pnns_groups_1', label: 'Food group' },
  { key: 'energy_kcal', label: 'Energy (kcal)' },
  { key: 'sugars', label: 'Sugars' },
  { key: 'salt', label: 'Salt' },
  { key: 'existence_status', label: 'Status' },
];
