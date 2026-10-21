---
title: Brand scorecard
---

How completely the products we hold are filled in, for brands with at least 30 products. Coverage is counted by this project on seven fields: a nutrition table, a Nutri-Score, a NOVA group, a quantity, an ingredients list, at least one category and at least one label. A brand with every field on every product scores 7 per product. It describes the products *we hold* (see [About](/about)), not a brand's whole range, and it is not the completeness score of Open Food Facts.

<Dropdown name=scope title="Products" defaultValue="all">
  <DropdownOption value="all" valueLabel="All markets" />
  <DropdownOption value="india" valueLabel="India" />
</Dropdown>

```sql brands
select
  brand_name,
  n_products,
  coverage_points,
  round(coverage_points * 1.0 / n_products, 2) as coverage_per_product,
  round(100.0 * n_with_nutrition / n_products, 0) as pct_nutrition,
  round(100.0 * n_with_nutriscore / n_products, 0) as pct_nutriscore,
  round(100.0 * n_with_nova / n_products, 0) as pct_nova,
  round(100.0 * n_with_quantity / n_products, 0) as pct_quantity,
  round(100.0 * n_with_ingredients / n_products, 0) as pct_ingredients,
  round(100.0 * n_with_categories / n_products, 0) as pct_categories,
  round(100.0 * n_with_labels / n_products, 0) as pct_labels
from site.brand_scorecard
where scope = '${inputs.scope.value}'
order by coverage_per_product desc, n_products desc
```

{#if brands.length === 0}

No brand reaches 30 products in this selection yet.

{:else}

<BarChart data={brands} x=brand_name y=coverage_per_product swapXY=true title="Coverage per product (7 = every field filled)" sort=false chartAreaHeight=600 />

<DataTable data={brands} rows=25 search=true>
  <Column id=brand_name title="Brand" />
  <Column id=n_products title="Products" fmt=num0 />
  <Column id=coverage_per_product title="Coverage per product" fmt=num2 contentType=colorscale />
  <Column id=pct_nutrition title="% nutrition" />
  <Column id=pct_nutriscore title="% Nutri-Score" />
  <Column id=pct_nova title="% NOVA" />
  <Column id=pct_quantity title="% quantity" />
  <Column id=pct_ingredients title="% ingredients" />
  <Column id=pct_categories title="% categories" />
  <Column id=pct_labels title="% labels" />
</DataTable>

{/if}

<small>Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/).</small>
