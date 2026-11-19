"""Turn a supported Chinese BI question into a parameterized read-only query."""

import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from textwrap import dedent


MONTH_PATTERN = re.compile(
    r"(?<![0-9])([0-9]{4})\s*(?:-\s*([0-9]{1,2})(?![0-9/-])"
    r"|年\s*([0-9]{1,2})\s*月(?!\s*[0-9]{1,2}\s*日))"
)
DATE_HINT = re.compile(r"(?<![0-9])[0-9]{4}\s*[-/年]")
RANK_LIMIT = re.compile(r"前\s*([0-9]{1,2})(?![0-9]|[.,/][0-9])")

MONTHLY_SALES = """
    SELECT month, SUM(order_count) AS order_count, SUM(units) AS units,
           SUM(net_amount_cents) AS net_amount_cents
    FROM ads_monthly_channel
    {month_filter}
    GROUP BY month
    ORDER BY month
"""

CHANNEL_RANKING = """
    SELECT channel, SUM(order_count) AS order_count, SUM(units) AS units,
           SUM(net_amount_cents) AS net_amount_cents
    FROM ads_monthly_channel
    {month_filter}
    GROUP BY channel
    ORDER BY net_amount_cents DESC, channel
"""

CATEGORY_TOP_PRODUCTS = """
    WITH product_sales AS (
        SELECT p.category, p.product_id, p.name, SUM(f.quantity) AS units,
               SUM(f.net_amount_cents) AS net_amount_cents
        FROM fact_order_item AS f
        JOIN dim_product AS p ON p.product_id = f.product_id
        {date_filter}
        GROUP BY p.category, p.product_id, p.name
    ),
    ranked AS (
        SELECT category, product_id, name, units, net_amount_cents,
               RANK() OVER (PARTITION BY category ORDER BY units DESC) AS sales_rank
        FROM product_sales
    )
    SELECT category, product_id, name, units, net_amount_cents, sales_rank
    FROM ranked
    WHERE sales_rank <= ?
    ORDER BY category, sales_rank, product_id
"""

CUSTOMERS_WITHOUT_ORDERS = """
    SELECT c.customer_id, c.name
    FROM dim_customer AS c
    LEFT JOIN fact_order_item AS f ON f.customer_id = c.customer_id {date_filter}
    WHERE f.order_id IS NULL
    ORDER BY c.customer_id
"""

UNSOLD_PRODUCTS = """
    SELECT p.product_id, p.name, p.category
    FROM dim_product AS p
    LEFT JOIN fact_order_item AS f ON f.product_id = p.product_id {date_filter}
    WHERE f.order_id IS NULL
    ORDER BY p.category, p.product_id
"""


def read_month(question: str) -> str | None:
    matches = list(MONTH_PATTERN.finditer(question))
    if DATE_HINT.search(MONTH_PATTERN.sub("", question)):
        raise ValueError("月份请使用 YYYY-MM 或 YYYY年M月，例如 2026-03。")
    if len(matches) > 1:
        raise ValueError("每次查询只支持一个月份。")
    if not matches:
        if re.search(r"本月|上月|当月|今年|去年|[0-9]+\s*月", question):
            raise ValueError("请给出具体年月，例如 2026-03。")
        return None

    year, month_iso, month_cn = matches[0].groups()
    month = int(month_iso or month_cn)
    if int(year) == 0 or not 1 <= month <= 12:
        raise ValueError("年份须大于 0000，月份须在 1 到 12 之间。")
    return f"{year}-{month:02d}"


def read_rank_limit(question: str) -> int:
    if "前" not in question:
        return 3
    matches = RANK_LIMIT.findall(question)
    if not matches or len(matches) > 1 or not 1 <= int(matches[0]) <= 20:
        raise ValueError("品类排行的名次请使用 1 到 20 之间的阿拉伯数字，例如前 3。")
    return int(matches[0])


def select_tool(question: str) -> str:
    matches = []
    if "客户" in question and re.search(r"未下单|没有?下单|无订单", question):
        matches.append("customers_without_orders")
    if "商品" in question and re.search(r"未售|没有?售出|没有?卖出|零销量", question):
        matches.append("unsold_products")
    if "品类" in question and re.search(r"销量|畅销", question):
        matches.append("category_top_products")
    if "渠道" in question and re.search(r"排行|排名|最好|最高|销售额|卖得|表现", question):
        matches.append("channel_ranking")
    if re.search(r"月度销售|每月销售|销售趋势|月报|月销售额", question):
        matches.append("monthly_sales")
    if len(matches) > 1:
        raise ValueError("一次问一种指标，例如「2026-03 渠道排行」。")
    if not matches:
        raise ValueError("可查询月度销售趋势、渠道排行、品类销量前 N、未下单客户或未售商品。")
    return matches[0]


def prepare_query(tool: str, question: str, month: str | None) -> tuple[str, list]:
    if tool in ("monthly_sales", "channel_ranking"):
        template = MONTHLY_SALES if tool == "monthly_sales" else CHANNEL_RANKING
        return template.format(month_filter="WHERE month = ?" if month else ""), [month] if month else []

    # ISO dates sort lexically. Day 31 is a valid upper bound even for shorter months.
    dates = [f"{month}-01", f"{month}-31"] if month else []
    date_condition = "f.order_date BETWEEN ? AND ?" if dates else ""
    if tool == "category_top_products":
        sql = CATEGORY_TOP_PRODUCTS.format(date_filter=f"WHERE {date_condition}" if dates else "")
        return sql, [*dates, read_rank_limit(question)]

    template = CUSTOMERS_WITHOUT_ORDERS if tool == "customers_without_orders" else UNSOLD_PRODUCTS
    return template.format(date_filter=f"AND {date_condition}" if dates else ""), dates


def ask(db_path: Path, question: str) -> dict:
    """Route a question, execute the matching tool and expose its SQL and bindings."""
    question = unicodedata.normalize("NFKC", question).strip()
    tool = select_tool(question)
    month = read_month(question)
    sql, parameters = prepare_query(tool, question, month)
    sql = dedent(sql).strip()
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        cursor = connection.execute(sql, parameters)
        return {
            "tool": tool,
            "parameters": parameters,
            "sql": sql,
            "columns": [column[0] for column in cursor.description],
            "rows": [list(row) for row in cursor],
        }
