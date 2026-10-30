# TO-DO LIST — stock_barcodes_picking / stock_barcodes_mrp 性能优化

> 基线来自实际测量（odoo19 开发库，每次请求前 flush + 清 ORM 缓存，近似一次 HTTP 请求的冷缓存）。
> 交付原则：每项独立提交、独立回归，不做"顺手重构"。

## 基线数据

| 场景 | 查询数 | 耗时 |
|---|---|---|
| picking 扫产品（30 行） | 30 | 21 ms |
| picking 扫序列号（30 行，含状态回传） | 27 | 12 ms |
| picking 扫序列号（10 产品 / 500 行） | 39 | 33 ms |
| picking `get_scan_state`：30 / 200 / 500 / 1000 行 | 16 / 25 / 25 / 35 | 10 / 19 / 24 / 37 ms |
| picking 校验 500 行（核心 `button_validate`） | 3066 | 2194 ms |
| MRP `get_scan_state`：5→50 组件 | 18（恒定） | 11~14 ms |
| MRP 扫组件（产品码+SN，20 组件） | 57 | 28 ms |
| MRP `_auto_fill_components`：5 / 10 / 20 / 50 组件 | 63 / 103 / 183 / 424 | 33 / 56 / 94 / 218 ms |

单次 picking 扫码 SQL 分布（29 条）：`stock_quant` 6、`stock_move_line` 6、`stock_picking` 3、`stock_location` 4、`stock_lot` 2、`product_product` 2~3。

## P1（本轮执行）

- [x] **P1-B picking `get_scan_state` 一次性批量读取 —— 已完成**
  - 位置：`stock_barcodes_picking/wizard/stock_barcodes_picking.py` → `get_scan_state`、`_compute_totals`
  - 问题：按 move 逐个取 `mv.move_line_ids`，每个 move 形成独立预取组 → 每 move 一条（甚至多条）SELECT；10 个 move 就有 10 条 `stock_lot` 查询
  - 方案：进循环前取一次 `picking.move_line_ids`，一次性预热 `lot_id.name` / `result_package_id.name` / 产品展示名，再按 `move_id` 分组复用；`_compute_totals` 复用同一份行集合
  - 实测（同一临时库、同脚本 A/B 对比，含冷缓存）：

    | 单据规模 | 改动前 | 改动后 |
    |---|---|---|
    | 1 move / 30 行 | 22 查询 / 12.2 ms | 22 查询 / 12.7 ms |
    | 10 move / 200 行 | 25 查询 / 14.7 ms | 16 查询 / 12.4 ms |
    | 10 move / 500 行 | 25 查询 / 22.4 ms | 16 查询 / 19.8 ms |
    | 20 move / 1000 行 | 35 查询 / 35.2 ms | 16 查询 / 29.5 ms |

  - 回归：picking 44 tests 全绿；覆盖"装包分组 / 保留 SN（barcode_show_reserved_sns）/ 行数量汇总 / total_done"
  - 备注：小单据（30 行）持平，随行数增长收益放大（查询数与 move 数解耦）

- [x] **P1-A MRP `_auto_fill_components` 批量写入 —— 已测量否决**
  - 结论：**不改**。该方法的成本几乎全部来自核心 `mrp.production._compute_components_availability` → `stock.move.forecast_availability` 的逐 move 重算（每组件约 7 条 `stock_quant` 查询），与"逐行 ORM 写"关系不大。
  - 实测（同一临时库 A/B）：

    | 组件数 | 原实现 | 按数量分组合并写 | 合并写 + 末尾单次 picked 写 |
    |---|---|---|---|
    | 5 | 55 查询 / 35.8 ms | 67 / 37.4 | 67 / 37.4 |
    | 10 | 90 / 61.3 | 117 / 66.0 | 117 / 66.0 |
    | 20 | 160 / 103.6 | 217 / 121.2 | 217 / 121.2 |
    | 50 | 370 / 245.8 | 517 / 301.9 | 517 / 301.9 |

  - 变体 `write(..., flush=False)`：Odoo 19 的 `Model.write()` 已无 `flush` 参数（`TypeError`），无法合并 flush 后的重算。
  - 若要真正降低该成本，只能减少 `forecast_availability` 的失效次数（例如在 mrp 侧提供跳过可用性校验的上下文），属于跨模块改动，不在本模块范围内 —— 若后续确认需要，单列为独立议题。

## P2（下一轮）

- [ ] **P2-A 扫描器前置过滤，去掉每次扫码的固定无效查询**
  - `_scan_location` / `_scan_dest_location`：作业类型未开启对应配置时直接 `return False`（省 2 条/次）
  - `_scan_picking`：`search` + `search_count` 合并为一次 `search`，Python 侧区分 active/inactive（省 1 条/次）
  - `_scan_product`：仅在产品阶段或当前无产品上下文时查询
  - 预期：29 → 约 24 查询/次（约 10~15%）
- [ ] **P2-B quant 查询合并 + 库位裁剪**
  - `_compute_qty_available` 与 `_get_serial_pick_error` 合并为一次 quant 读取（复用结果）
  - `_get_serial_pick_error` 的 quant 域按源库位子树（`child_of`）裁剪；"当前在哪"提示复用同一批结果
  - 预期：单次扫码 quant 查询 6 → 2~3

## P3（按需）

- [ ] **P3-A** `_process_stock_move_line` 复用 `moves.mapped("move_line_ids")`，`other_lines` 用集合差（省 2 条/次）
- [ ] **P3-B** 大单据状态回传：`get_scan_state` 增加 `since`/`version` 只回传变化行；>200 行时分页/虚拟滚动
- [ ] **P3-C** 前端扫码队列：RPC 进行中不再丢弃 `barcode_scanned` 事件（`picking_scan_app.esm.js`、`mrp_scan_app.esm.js`）
- [ ] **P3-D** 校验前预热 `picking.move_ids` / `move_line_ids` 预取，减少核心 `button_validate` 的碎查询（500 行实测 3066 查询 / 2.2 s，主体在核心）

## 不做

- `_compute_totals` 不加 `store=True`（TransientModel 无收益）
- 不把 `get_scan_state` 拆成两个 RPC（现状已是 1 次往返）
- 不为 `stock.lot.name` 额外建索引（核心已是 trigram；SN 库到千万级再评估）

## 非性能项（记录，另行决策）

- MRP 未选组件行/未扫组件产品码时，直接扫组件 SN 会报 "Barcode not found"（`_scan_lot` 无 product 时直接返回，不走全局回退）。属"先选产品再扫 SN"的设计约束，但与 picking 的"扫 SN 自动匹配产品"体验不一致。

## 验收方式

1. `pylint-odoo` 门禁（仓库内 `.pylintrc` / `.pylintrc-mandatory`）
2. 临时库全量测试：`stock_barcodes_picking`、`stock_barcodes_mrp`
3. 重跑同一套测量脚本，对比上面基线表（记录改动后的查询数与耗时）
