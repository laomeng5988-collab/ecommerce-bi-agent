PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_customer (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS src_order (
    order_id INTEGER PRIMARY KEY,
    order_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES dim_customer(customer_id),
    channel TEXT NOT NULL CHECK (channel IN ('APP', 'WEB', '小程序'))
);

-- 来源可能有脏数据，同一个订单行可以被重复投递或更正。
CREATE TABLE IF NOT EXISTS raw_order_item (
    ingest_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no INTEGER NOT NULL,
    row_no INTEGER NOT NULL,
    order_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    net_amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    source_version INTEGER NOT NULL,
    UNIQUE (batch_no, row_no)
);

CREATE INDEX IF NOT EXISTS ix_raw_item_version
    ON raw_order_item(order_id, line_no, source_version DESC, ingest_id DESC);

CREATE TABLE IF NOT EXISTS fact_order_item (
    order_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES dim_customer(customer_id),
    product_id INTEGER NOT NULL REFERENCES dim_product(product_id),
    channel TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    net_amount_cents INTEGER NOT NULL CHECK (net_amount_cents >= 0),
    PRIMARY KEY (order_id, line_no),
    FOREIGN KEY (order_id) REFERENCES src_order(order_id)
);

CREATE INDEX IF NOT EXISTS ix_fact_date_channel ON fact_order_item(order_date, channel);
CREATE INDEX IF NOT EXISTS ix_fact_customer ON fact_order_item(customer_id);
CREATE INDEX IF NOT EXISTS ix_fact_product ON fact_order_item(product_id);

CREATE TABLE IF NOT EXISTS etl_reject (
    order_id INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    ingest_id INTEGER NOT NULL REFERENCES raw_order_item(ingest_id),
    reason TEXT NOT NULL,
    PRIMARY KEY (order_id, line_no)
);

CREATE TABLE IF NOT EXISTS etl_checkpoint (
    pipeline TEXT PRIMARY KEY,
    last_ingest_id INTEGER NOT NULL
);

INSERT OR IGNORE INTO etl_checkpoint VALUES ('order_item', 0);

CREATE VIEW IF NOT EXISTS ads_monthly_channel AS
SELECT substr(order_date, 1, 7) AS month,
       channel,
       COUNT(DISTINCT order_id) AS order_count,
       SUM(quantity) AS units,
       SUM(net_amount_cents) AS net_amount_cents
FROM fact_order_item
GROUP BY substr(order_date, 1, 7), channel;
