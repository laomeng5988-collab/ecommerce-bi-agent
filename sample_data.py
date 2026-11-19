from datetime import date, timedelta
from random import Random

CATEGORIES = ("手机数码", "家居日用", "食品饮料", "办公文具")
CHANNELS = ("APP", "WEB", "小程序")


def sample_data():
    rng = Random(20261119)
    customers = [(i, f"客户{i:03}") for i in range(1, 201)]
    products = [
        (i, f"{CATEGORIES[(i - 1) // 10]}-{i:02}", CATEGORIES[(i - 1) // 10])
        for i in range(1, 41)
    ]
    orders = []
    first_batch = []
    for order_id in range(1, 1801):
        order_date = date(2026, 1, 1) + timedelta(days=rng.randrange(181))
        orders.append((order_id, order_date.isoformat(), rng.randint(1, 170), rng.choice(CHANNELS)))
        item_count = 2 if order_id <= 1200 else 1
        for line in range(1, item_count + 1):
            product = rng.randint(1, 37)
            quantity = rng.randint(1, 5)
            amount = rng.randint(990, 129900) * quantity
            first_batch.append((order_id, line, product, quantity, amount, " PAID ", 1))

    first_batch.extend([
        first_batch[0],  # 同一业务键、同一版本的重复投递
        (2, 3, 999, 1, 1599, "paid", 1),
        (3, 3, 1, 0, 1599, "paid", 1),
        (9999, 1, 1, 1, 1599, "paid", 1),
    ])
    second_batch = [
        (1, 1, 1, 0, 0, "cancelled", 2),  # 已支付行被取消
        (2, 3, 1, 2, 3598, "paid", 2),  # 商品字段修正
        (3, 3, 1, 0, 1599, "paid", 2),  # 质检错误仍然存在
        (4, 3, 2, 1, 2999, "paid", 3),  # 新增有效明细
        (4, 3, 2, 5, 14995, "paid", 2),  # 更晚到达，但业务版本更旧
    ]
    return customers, products, orders, {1: first_batch, 2: second_batch}
