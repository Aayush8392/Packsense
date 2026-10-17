{{ config(materialized='table') }}

-- One row per label tag seen in the history, resolved against OFF's labels taxonomy (macro tag_dimension: tag, name, ambiguous, none).
{{ tag_dimension('bridge_product_label', 'label_tag', 'labels', 'label') }}
