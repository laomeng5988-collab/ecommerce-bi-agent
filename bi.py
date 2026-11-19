import argparse
from contextlib import closing
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys

from bi_agent import ask
from mysql_export import export_mysql
from sample_data import sample_data

PROJECT = Path(__file__).resolve().parent
SCHEMA = (PROJECT / "schema.sql").read_text(encoding="utf-8")
INCREMENTAL_SQL = (PROJECT / "incremental.sql").read_text(encoding="utf-8")


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def load_batch(db, number):
    customers, products, orders, batches = sample_data()
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.executemany("INSERT OR IGNORE INTO dim_customer VALUES (?, ?)", customers)
        db.executemany("INSERT OR IGNORE INTO dim_product VALUES (?, ?, ?)", products)
        db.executemany("INSERT OR IGNORE INTO src_order VALUES (?, ?, ?, ?)", orders)
        count_before = db.total_changes
        loaded_rows = {
            row[0] for row in db.execute("SELECT row_no FROM raw_order_item WHERE batch_no = ?", (number,))
        }
        db.executemany(
            """INSERT INTO raw_order_item
               (batch_no, row_no, order_id, line_no, product_id, quantity,
                net_amount_cents, status, source_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ((number, row_no, *row) for row_no, row in enumerate(batches[number], 1)
             if row_no not in loaded_rows),
        )
    return db.total_changes - count_before


def refresh(db):
    with db:
        db.execute("BEGIN IMMEDIATE")
        watermark = db.execute(
            "SELECT last_ingest_id FROM etl_checkpoint WHERE pipeline = 'order_item'"
        ).fetchone()[0]
        upper_bound = db.execute("SELECT COALESCE(MAX(ingest_id), 0) FROM raw_order_item").fetchone()[0]
        rows = db.execute(INCREMENTAL_SQL, {
            "last_ingest_id": watermark,
            "end_ingest_id": upper_bound,
        }).fetchall()

        affected_keys = [(row["order_id"], row["line_no"]) for row in rows]
        db.executemany("DELETE FROM fact_order_item WHERE order_id = ? AND line_no = ?", affected_keys)
        db.executemany("DELETE FROM etl_reject WHERE order_id = ? AND line_no = ?", affected_keys)

        valid_rows = [row for row in rows if not row["reject_reason"] and row["status"] == "paid"]
        rejected_rows = [row for row in rows if row["reject_reason"]]
        db.executemany(
            """INSERT INTO fact_order_item
               (order_id, line_no, order_date, customer_id, product_id, channel, quantity, net_amount_cents)
               VALUES (:order_id, :line_no, :order_date, :customer_id, :product_id, :channel,
                       :quantity, :net_amount_cents)""",
            map(dict, valid_rows),
        )
        db.executemany(
            """INSERT INTO etl_reject VALUES (:order_id, :line_no, :ingest_id, :reject_reason)""",
            map(dict, rejected_rows),
        )
        db.execute(
            "UPDATE etl_checkpoint SET last_ingest_id = ? WHERE pipeline = 'order_item'",
            (upper_bound,),
        )
    return {
        "水位": [watermark, upper_bound], "重算明细": len(rows), "有效": len(valid_rows),
        "拒绝": len(rejected_rows), "取消": len(rows) - len(valid_rows) - len(rejected_rows),
    }


def check(db):
    raw_events = db.execute("SELECT COUNT(*) FROM raw_order_item").fetchone()[0]
    fact = tuple(db.execute(
        """SELECT COUNT(DISTINCT order_id), COALESCE(SUM(quantity), 0),
                  COALESCE(SUM(net_amount_cents), 0) FROM fact_order_item"""
    ).fetchone())
    report = tuple(db.execute(
        """SELECT COALESCE(SUM(order_count), 0), COALESCE(SUM(units), 0),
                  COALESCE(SUM(net_amount_cents), 0) FROM ads_monthly_channel"""
    ).fetchone())
    pending = db.execute(
        """SELECT COUNT(*) FROM raw_order_item
           WHERE ingest_id > (SELECT last_ingest_id FROM etl_checkpoint WHERE pipeline = 'order_item')"""
    ).fetchone()[0]
    rejects = dict(db.execute("SELECT reason, COUNT(*) FROM etl_reject GROUP BY reason").fetchall())
    integrity_ok = db.execute("PRAGMA foreign_key_check").fetchone() is None
    reconciliation_ok = fact == report
    summary = {
        "原始事件": raw_events, "待处理事件": pending,
        "有效订单": fact[0], "销量": fact[1], "净销售额（分）": fact[2],
        "当前拒绝": rejects, "报表对账": reconciliation_ok, "外键校验": integrity_ok,
    }
    return summary, bool(raw_events) and pending == 0 and reconciliation_ok and integrity_ok


def emit(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_answer(answer):
    print(f"工具  {answer['tool']}    参数  {answer['parameters']}")
    columns = answer["columns"]
    print(" | ".join(columns))
    for row in answer["rows"][:12]:
        values = [
            f"{Decimal(value) / 100:,.2f} 元" if col == "net_amount_cents" else str(value)
            for col, value in zip(columns, row)
        ]
        print(" | ".join(values))
    if not answer["rows"]:
        print("没有符合条件的数据。")
    elif len(answer["rows"]) > 12:
        print(f"共 {len(answer['rows'])} 行。使用 --json 查看全部。")


def main():
    parser = argparse.ArgumentParser(description="本地电商 BI 数据库与查询 Agent")
    parser.add_argument("--db", type=Path, default=Path("sales_bi.sqlite3"), help="SQLite 数据库路径")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="分两批入库、增量处理并对账")
    load = commands.add_parser("load", help="导入指定模拟批次")
    load.add_argument("batch", type=int, choices=(1, 2))
    commands.add_parser("etl", help="处理新入库事件")
    commands.add_parser("check", help="检查处理进度、数据质量与报表对账")
    export = commands.add_parser("mysql-export", help="将已处理的销售快照导出为 MySQL 演练脚本")
    export.add_argument("output", type=Path, help="新建的 SQL 文件路径")
    query = commands.add_parser("ask", help="向只读查询 Agent 提问")
    query.add_argument("question")
    query.add_argument("--json", action="store_true", help="输出完整结果、SQL 和绑定参数")
    args = parser.parse_args()

    try:
        if args.command == "ask":
            answer = ask(args.db, args.question)
            (emit if args.json else print_answer)(answer)
            return 0
        if args.command in ("check", "mysql-export") and not args.db.is_file():
            raise ValueError("数据库不存在，请先运行 demo。")
        with closing(connect(args.db)) as db:
            if args.command in ("demo", "load", "etl"):
                db.executescript(SCHEMA)
            if args.command == "load":
                emit({"批次": args.batch, "新增事件": load_batch(db, args.batch)})
            elif args.command == "etl":
                emit(refresh(db))
            elif args.command == "demo":
                for batch in (1, 2):
                    emit({"批次": batch, "新增事件": load_batch(db, batch), "ETL": refresh(db)})
                emit({"再次执行 ETL": refresh(db)})
            elif args.command == "mysql-export":
                db.execute("BEGIN")
                _, ok = check(db)
                if not ok:
                    raise ValueError("请先完成数据处理与对账。")
                export_mysql(db, args.output)
                print(f"已生成 {args.output}")
            if args.command in ("check", "demo"):
                db.execute("BEGIN")
                summary, ok = check(db)
                emit(summary)
                return 0 if ok else 1
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"错误  {exc}\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
