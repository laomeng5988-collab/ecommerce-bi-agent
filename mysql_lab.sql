-- 在空的练习数据库中执行。金额字段单位是分。
CREATE TABLE dim_customer (
    customer_id INT PRIMARY KEY,
    name VARCHAR(80) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE dim_product (
    product_id INT PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    category VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE fact_order_item (
    order_id INT NOT NULL,
    line_no INT NOT NULL,
    order_date DATE NOT NULL,
    customer_id INT NOT NULL,
    product_id INT NOT NULL,
    channel VARCHAR(20) NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    net_amount_cents BIGINT NOT NULL CHECK (net_amount_cents >= 0),
    PRIMARY KEY (order_id, line_no),
    FOREIGN KEY (customer_id) REFERENCES dim_customer(customer_id),
    FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    INDEX ix_fact_date_channel (order_date, channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- SNAPSHOT_DATA

CREATE SQL SECURITY INVOKER VIEW ads_monthly_channel AS
SELECT DATE_FORMAT(order_date, '%Y-%m') AS month, channel,
       COUNT(DISTINCT order_id) AS order_count,
       SUM(quantity) AS units, SUM(net_amount_cents) AS net_amount_cents
FROM fact_order_item
GROUP BY DATE_FORMAT(order_date, '%Y-%m'), channel;

-- 月度趋势与跨库对账
SELECT month, SUM(order_count) AS orders, SUM(units) AS units,
       SUM(net_amount_cents) AS net_amount_cents
FROM ads_monthly_channel
GROUP BY month
ORDER BY month;

SELECT SUM(order_count) AS orders, SUM(units) AS units,
       SUM(net_amount_cents) AS net_amount_cents
FROM ads_monthly_channel;

-- 保留全部客户，找从未产生有效销售的客户。
SELECT COUNT(*) AS customers_without_orders
FROM dim_customer AS c
LEFT JOIN fact_order_item AS f ON f.customer_id = c.customer_id
WHERE f.order_id IS NULL;

-- RIGHT JOIN 保留右侧全部商品。交换表顺序后可以写成 LEFT JOIN。
SELECT COUNT(*) AS unsold_products
FROM fact_order_item AS f
RIGHT JOIN dim_product AS p ON f.product_id = p.product_id
WHERE f.order_id IS NULL;

-- 每个品类内的商品销量前 3，保留并列。
WITH product_sales AS (
    SELECT p.category, p.product_id, p.name, SUM(f.quantity) AS units
    FROM fact_order_item AS f
    JOIN dim_product AS p ON f.product_id = p.product_id
    WHERE f.order_date >= '2026-03-01' AND f.order_date < '2026-04-01'
    GROUP BY p.category, p.product_id, p.name
),
ranked AS (
    SELECT *, RANK() OVER (PARTITION BY category ORDER BY units DESC) AS sales_rank
    FROM product_sales
)
SELECT category, product_id, name, units, sales_rank
FROM ranked
WHERE sales_rank <= 3
ORDER BY category, sales_rank, product_id;

EXPLAIN
SELECT SUM(net_amount_cents)
FROM fact_order_item
WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01'
  AND channel = 'APP';
