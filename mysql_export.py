from pathlib import Path

TABLES = {
    "dim_customer": ("customer_id", "name"),
    "dim_product": ("product_id", "name", "category"),
    "fact_order_item": (
        "order_id", "line_no", "order_date", "customer_id", "product_id",
        "channel", "quantity", "net_amount_cents",
    ),
}


def sql_literal(value):
    if isinstance(value, int):
        return str(value)
    return f"CONVERT(X'{value.encode('utf-8').hex()}' USING utf8mb4)"


def export_mysql(db, output):
    script = Path(__file__).with_name("mysql_lab.sql").read_text(encoding="utf-8")
    before, after = script.split("-- SNAPSHOT_DATA", maxsplit=1)
    with output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(before)
        file.write("START TRANSACTION;\n")
        for table, fields in TABLES.items():
            columns = ", ".join(fields)
            for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY {columns}"):
                values = ", ".join(map(sql_literal, row))
                file.write(f"INSERT INTO {table} ({columns}) VALUES ({values});\n")
        file.write("COMMIT;\n")
        file.write(after)
