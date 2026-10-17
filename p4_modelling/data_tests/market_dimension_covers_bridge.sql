-- Every market used by the bridge exists in dim_market, and the one target market (India) is flagged.
select b.market_code
from (select distinct market_code from {{ ref('bridge_product_market') }}) as b
left join {{ ref('dim_market') }} as m on b.market_code = m.market_code
where m.market_code is null
   or (m.market_code = 'en:india' and m.is_target_market <> 1)
   or (m.market_code <> 'en:india' and m.is_target_market <> 0)
