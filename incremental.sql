-- 只处理新入库事件触达的业务键，再到该键的历史中选择当前版本。
-- source_version 来自业务侧，晚到的旧版本不能覆盖已处理的新版本。
WITH touched AS (
    SELECT DISTINCT order_id, line_no
    FROM raw_order_item
    WHERE ingest_id > :last_ingest_id AND ingest_id <= :end_ingest_id
),
ranked AS (
    SELECT raw.*,
           ROW_NUMBER() OVER (
               PARTITION BY raw.order_id, raw.line_no
               ORDER BY raw.source_version DESC, raw.ingest_id DESC
           ) AS version_rank
    FROM touched
    JOIN raw_order_item AS raw USING (order_id, line_no)
    WHERE raw.ingest_id <= :end_ingest_id
)
SELECT r.order_id, r.line_no, r.ingest_id, r.product_id, r.quantity, r.net_amount_cents,
       o.order_date, o.customer_id, o.channel, lower(trim(r.status)) AS status,
       CASE
           WHEN o.order_id IS NULL THEN 'missing_order'
           WHEN lower(trim(r.status)) NOT IN ('paid', 'cancelled') THEN 'unknown_status'
           WHEN lower(trim(r.status)) = 'paid' AND p.product_id IS NULL THEN 'missing_product'
           WHEN lower(trim(r.status)) = 'paid' AND r.quantity <= 0 THEN 'invalid_quantity'
           WHEN lower(trim(r.status)) = 'paid' AND r.net_amount_cents < 0 THEN 'invalid_amount'
       END AS reject_reason
FROM ranked AS r
LEFT JOIN src_order AS o ON o.order_id = r.order_id
LEFT JOIN dim_product AS p ON p.product_id = r.product_id
WHERE r.version_rank = 1
ORDER BY r.order_id, r.line_no;
