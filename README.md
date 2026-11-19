# 电商销售数仓与 BI 查询 Agent

用模拟订单练习 BI 数据开发。主流程在本地 SQLite 运行，涵盖建表、增量 ETL、报表对账和中文查询。MySQL 部分把同一份处理结果导入练习库，可复跑报表 SQL。

## 五分钟跑通

解压后在项目目录打开 PowerShell。需要 Python 3.10 或更新版本，使用 Python 自带的 SQLite，无需安装第三方包。Windows 若使用 `py` 命令，将下面的 `python` 替换成 `py -3`。

```powershell
python bi.py demo
python bi.py ask "月度销售趋势"
python bi.py ask "2026年3月哪个渠道卖得最好"
python bi.py ask "2026-03 各品类销量前3" --json
python bi.py ask "未下单客户"
python bi.py ask "未售商品"
```

默认生成 `sales_bi.sqlite3`。完整演示会写入 **3,009 条来源事件**，得到 **3,001 条有效明细、1,800 个订单、销量 8,919 件、模拟净销售额 5,955,497.38 元**。待处理事件为 0，剩余两条异常分别是无效数量、找不到订单。模拟数据中有 30 名未产生有效销售的客户与 3 件未售商品。

`--json` 显示工具名、绑定参数、SQL 和完整结果。每个工具都可带 YYYY-MM 或“2026年3月”，省略月份默认查询全量。品类排行默认前 3 名，支持前 1 至 20 名。“未下单”在本项目里按查询期间没有有效已支付明细定义。

## 把增量过程拆开看

```powershell
python bi.py --db walkthrough.sqlite3 load 1
python bi.py --db walkthrough.sqlite3 etl
python bi.py --db walkthrough.sqlite3 check
python bi.py --db walkthrough.sqlite3 load 2
python bi.py --db walkthrough.sqlite3 etl
python bi.py --db walkthrough.sqlite3 check
python bi.py --db walkthrough.sqlite3 etl
```

首次水位从 0 到 3004，生成 3,000 条有效明细，隔离 3 条异常。第二次水位到 3009，只重算 4 个受影响的订单行。订单 1 的第 1 行因取消而从事实表移除，订单 2 的第 3 行补齐有效商品后恢复，订单 4 的第 3 行采用版本 3，即使版本 2 后到。第三次执行重算 0 行。重新导入同一个批次会新增 0 条事件。重做全流程时可用新的数据库文件名。

| 文件 | 复盘时看什么 |
| --- | --- |
| `schema.sql` | 主键、外键、订单明细粒度、复合索引及月度渠道视图 |
| `sample_data.py` | 固定随机种子、两批模拟事件和故障用例 |
| `incremental.sql` | 入库水位圈定受影响的键，业务版本确定应采用哪条记录 |
| `bi.py` | 批次导入、事务内更新事实与异常记录、推进水位和对账 |
| `bi_agent.py` | 中文问句匹配、月份和 Top N 校验、固定查询工具、只读连接 |
| `mysql_lab.sql` 和 `mysql_export.py` | MySQL 建表、导出同一数据快照、左右连接及执行计划 |

维表包含客户和商品，事实表粒度是一条有效订单明细，报表视图粒度是“月份 × 渠道”。每单的日期、客户和渠道由订单头统一提供，因此可以把各渠道各自的去重订单数相加，得到当月总订单数。净销售额只汇总有效已支付明细，金额以整数分存储。取消行从事实表撤销，异常行进入拒绝表。本演练的订单头和两个维表在批次间固定，增量更新覆盖订单明细。中文 Agent 使用离线规则选择只读 SQL 工具。

## 在 MySQL 里复核

本地有 MySQL 8.0.16 或更新服务时，可选做这个练习。快照脚本已在 MySQL 9.4 验证。以下命令以本机已有账号为例。先从 SQLite 生成快照脚本，再导入一个空的练习库。

```powershell
python bi.py mysql-export mysql_snapshot.sql
mysql -u root -p --default-character-set=utf8mb4 -e "CREATE DATABASE bi_ecommerce_lab CHARACTER SET utf8mb4"
mysql -u root -p --default-character-set=utf8mb4 bi_ecommerce_lab -e "SOURCE mysql_snapshot.sql"
```

也可以在 MySQL Workbench 中选中空练习库后运行 `mysql_snapshot.sql`。脚本会建维表与事实表，导入 SQLite 结果，执行月报、总量核对、左右连接、窗口排名和 `EXPLAIN`。总量应为 `1800 / 8919 / 595549738`，依次对应订单数、销量和净销售额（分）。SQLite 负责增量处理和 Agent 查询，MySQL 用于建表与报表复核。

## 面试前过一遍

1. **两套顺序各解决什么？** `ingest_id` 判断哪些订单行刚收到新事件。`source_version` 决定同一个订单行的当前版本。ETL 在一个事务内更新事实表、异常表和水位，失败回滚后可以用原水位重跑。
2. **为何用 `COUNT(DISTINCT order_id)`？** 一单可能有多条明细。`COUNT(*)` 数的是明细，`SUM(quantity)` 是销量，`SUM(net_amount_cents)` 是净销售额。
3. **左右连接和条件写在哪里？** `LEFT JOIN` 保留左表，`RIGHT JOIN` 保留右表。查三月未下单客户时，把三月条件放进 `ON`，随后在 `WHERE` 判断事实表主键为空。将月份约束移到 `WHERE` 会过滤掉补成 NULL 的行。
4. **SQL 的逻辑处理顺序是什么？** 这类聚合查询通常先 `FROM/JOIN/ON`，再 `WHERE`、`GROUP BY`、`HAVING`，然后生成 `SELECT` 结果、排序和限制行数。窗口排名基于分组后的商品销量，项目在外层过滤名次。物理执行计划由优化器选择。
5. **如何保留并列？** `RANK()` 会保留并列并跳号，像 1、1、3。若题目规定恰好取 N 行，使用 `ROW_NUMBER()` 并在排序中指定稳定的商品 ID。复合索引是否被选用可查看 `EXPLAIN` 的 `key`，用实际计划解释优化器的决定。
6. **Agent 能做什么？** 以三月的品类 Top 3 演示问句到工具的映射。月份与 N 都经校验，绑定参数送进固定 SQL。把 `--json` 的 SQL 和参数展开，自己讲清楚筛选、分组、排名三个步骤。

可以用这段思路介绍项目。先交代这是 AI 辅助的模拟练习，再讲自己跑过和核对过的部分：“原始订单数据有重复投递和晚到更正。我先按订单明细粒度建模，再按水位找出需要更新的明细，用业务版本取最新记录。最后把清洗后的明细聚合成月度渠道报表，并用中文 Agent 查询固定指标。我用第二批的取消和晚到旧版本验证了重跑与去重逻辑。”
