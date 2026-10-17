{{ config(materialized='table') }}

-- One row per category tag seen in the history, resolved against OFF's categories taxonomy (macro tag_dimension: tag, name, ambiguous, none).
-- The hierarchy columns (parents, n_children, is_root) come from the taxonomy; the product tag lists already hold the ancestors.
{{ tag_dimension('bridge_product_category', 'category_tag', 'categories', 'category') }}
