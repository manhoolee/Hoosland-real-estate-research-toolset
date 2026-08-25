# 竞品数据结构

每个竞品建议记录：

`project_id, project_name, category, scope_id, distance_or_commute, product_type, unit_area_min, unit_area_max, asking_price, registered_price, transaction_price, total_price, launch_date, observation_date, inventory, sales, sell_through_period, customer_source, source_ids, confidence, notes`

`category` 只用：

- `DIRECT`：同客群、同总价、同购买时点；
- `SUBSTITUTE`：满足相近需求但板块/产品不同；
- `MISALIGNED`：常被提及但支付或产品不重叠；
- `WATCHLIST`：尚未入市或信息不足。

价格必须区分报价、备案与成交；去化必须说明观察期、推售套数和退订口径。距离说明是直线、道路还是通勤时间。
