# TO-DO LIST — stock_barcodes_picking / stock_barcodes_mrp 性能优化

> 任务清单 + 本次优化总结报告。
> 基线来自实际测量（odoo19 开发库，每次请求前 flush + 清 ORM 缓存，近似一次 HTTP 请求的冷缓存）。
> 交付原则：每项独立验证、独立回归，不做"顺手重构"。

---

# 一、本次优化总结报告

## 1. 结论摘要

| 维度 | 结论 |
|---|---|
| 是否存在性能瓶颈 | **有，但不是架构性问题**。热路径结构正确（每次扫码 1 次 RPC、状态随响应一起回传），瓶颈集中在"重复查询"和"逐行写"两类局部实现上 |
| 已优化 | 3 类：picking 状态快照批量读取、扫码器前置过滤 + quant 查询合并、前端扫码队列 |
| 已否决 | 2 类：MRP 自动填充批量化（实测更差）、picking 产品扫描前置跳过（收益不抵体验损失） |
| 整体效果 | 小单据 39.5 → 35.5 查询（约 -10%）；<br>大单据收益显著：1000 行单据状态快照 35 → 16 查询（约 -54%），查询数与单据行数解耦 |
| 回归情况 | picking 44 tests、MRP 111 tests 全绿；`pylint-odoo` 强制门禁无告警；JS `node --check` 通过 |
| 遗留事项 | 前端扫码队列需真机连扫验证（本环境无 Chromium，无法跑 tour） |

## 2. 瓶颈定位（实测证据）

单次 picking 扫码原始 SQL 分布（29 条）：`stock_quant` 6、`stock_move_line` 6、`stock_picking` 3、`stock_location` 4、`stock_lot` 2、`product_product` 2~3。

对应 4 个具体问题：

1. `get_scan_state` 按 move 逐个读取 `mv.move_line_ids`，每个 move 形成独立预取组 → 查询数随 move 数线性增长（10 move 时多出 10 条 `stock_lot` 查询）；
2. 每次扫码都无条件跑全部扫描器，即使作业类型没有开启"扫源/目的库位"，也照查一次 `stock.location`；`_scan_picking` 还多一次 `search_count`；
3. 同一批 quant 在一次扫码里被查两次（`_compute_qty_available` 与 `_get_serial_pick_error`）；
4. 前端在 RPC 在飞时**直接丢弃**新扫到的条码（`if (!barcode || this.state.scanning) return`），高速扫码枪连扫会掉码。

## 3. 优化项与效果

| 编号 | 优化内容 | 效果 | 状态 |
|---|---|---|---|
| P1-B | `get_scan_state` / `_compute_totals` 一次性批量读取，按 `move_id` 分组复用 | 1000 行：35 → 16 查询；500 行：25 → 16 | 已完成 |
| P2-A | `_scan_location` / `_scan_dest_location` 按配置短路；`_scan_picking` 合并 `search` + `search_count` | 每次扫码省 3 条 | 已完成 |
| P2-B | `_compute_qty_available` 返回 quant 集合，透传给 `action_confirm` → `_get_serial_pick_error` | 每次扫码省 1 条 quant | 已完成 |
| P3-C | 两个客户端改为扫码队列（`_scanQueue` + 单 worker 顺序出队），原逻辑改名 `_scanOne` | 不再丢码；仍为每次扫码 1 次 RPC | 已完成（待真机验证） |
| P3-A | `_process_stock_move_line` 复用一次 `move_line_ids` 读取 | 无查询收益（原 `mapped()` 已走预取缓存），仅去重复调用 | 已完成 |
| P1-A | MRP `_auto_fill_components` 批量化写 | 实测**更差**（查询 +40%），已回滚 | 否决（见下） |
| P2-A' | `_scan_product` 前置跳过 | 会让"扫别的产品条码切换产品"失效并丢失精确报错 | 否决 |

**整体前后对比**（同库同脚本，30 行单据，含状态回传，10 次扫码均值）：

| 版本 | 扫序列号 | 扫产品 |
|---|---|---|
| HEAD（未优化） | 39.5 查询 / 17.9 ms | 29 查询 / 14.2 ms |
| P1-B + P2 + P3 | 35.5 查询 / 15.6 ms | 26 查询 / 13.5 ms |

**规模扩展性对比**（picking `get_scan_state`）：

| 单据规模 | 改动前 | 改动后 |
|---|---|---|
| 1 move / 30 行 | 22 查询 / 12.2 ms | 22 查询 / 12.7 ms |
| 10 move / 200 行 | 25 / 14.7 ms | 16 / 12.4 ms |
| 10 move / 500 行 | 25 / 22.4 ms | 16 / 19.8 ms |
| 20 move / 1000 行 | 35 / 35.2 ms | 16 / 29.5 ms |

## 4. 否决项与证据（避免后人重复尝试）

**P1-A：MRP `_auto_fill_components` 批量化写 —— 不做**

| 组件数 | 原实现 | 按数量分组合并写 |
|---|---|---|
| 10 | 90 查询 / 61 ms | 117 / 66 |
| 20 | 160 / 104 ms | 217 / 121 |
| 50 | 370 / 246 ms | 517 / 302 |

根因：成本来自核心 `mrp.production._compute_components_availability` → `stock.move.forecast_availability` 的逐 move 重算（每组件约 7 条 `stock_quant` 查询），与"逐行 ORM 写"无关。合并写反而让失效重算次数不变、write 开销变大。
`write(..., flush=False)` 在 Odoo 19 已不可用（`TypeError`），无法合并 flush 后的重算。
如需继续，只能减少 `forecast_availability` 失效次数（mrp 侧上下文跳过可用性校验），属跨模块改动，单列议题。

## 5. 改动文件

| 文件 | 改动 |
|---|---|
| `stock_barcodes_picking/wizard/stock_barcodes_picking.py` | P1-B 批量读取、P2-A 扫描器短路、P2-B quant 复用、P3-A 去重 `mapped` |
| `stock_barcodes_picking/static/src/picking_scan_app.esm.js` | P3-C 扫码队列（`_scanQueue` / `_scanOne`） |
| `stock_barcodes_mrp/static/src/mrp_scan_app.esm.js` | P3-C 扫码队列（`_scanQueue` / `_scanOne`） |
| `TO-DO-LIST.md` | 本报告与任务清单 |

`stock_barcodes_mrp/wizard/stock_barcodes_mrp.py` 为**净无改动**（P1-A 已回滚）。

## 6. 验证记录

1. 临时库全新安装 + 全量测试：`stock_barcodes_picking` 44 tests、`stock_barcodes_mrp` 111 tests，无 FAIL；唯一异常是 `TestMrpScanAppTour.setUpClass`（环境缺 `/snap/bin/chromium`，非代码问题）。
2. `pylint-odoo` 强制门禁（`.pylintrc-mandatory`）：无告警。
3. 两个 JS 客户端 `node --check`：通过。
4. 性能数据全部为同库 A/B（`git stash` 切换）实测，排除库状态差异。
5. 临时库（`ot_p1` / `ot_p2` / `ot_p3`）与测量脚本均已清理，未留在仓库。

## 7. 遗留与风险

- **P3-C 需真机验证**：扫码队列改变了前端事件处理方式，建议用扫码枪 + 手机相机连续扫 20~30 个序列号，确认不掉码、不乱序、按钮禁用状态正常。
- 大单据（≥500 行）的状态回传仍为全量 payload，P3-B 未做（见下），如有真实大单据客户再启动。
- MRP 组件的可用性重算成本属核心 mrp 行为，本模块不处理。

---

# 二、任务清单（执行记录）

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

## P1（已完成）

- [x] **P1-B picking `get_scan_state` 一次性批量读取**
  - 位置：`stock_barcodes_picking/wizard/stock_barcodes_picking.py` → `get_scan_state`、`_compute_totals`
  - 问题：按 move 逐个取 `mv.move_line_ids`，每个 move 形成独立预取组 → 每 move 一条（甚至多条）SELECT；10 个 move 就有 10 条 `stock_lot` 查询
  - 方案：进循环前取一次 `picking.move_line_ids`，一次性预热 `lot_id.name` / `result_package_id.name` / 产品展示名，再按 `move_id` 分组复用；`_compute_totals` 复用同一份行集合
  - 实测：见上表"规模扩展性对比"
  - 回归：picking 44 tests 全绿；覆盖"装包分组 / 保留 SN（barcode_show_reserved_sns）/ 行数量汇总 / total_done"
  - 备注：小单据（30 行）持平，随行数增长收益放大（查询数与 move 数解耦）

- [x] **P1-A MRP `_auto_fill_components` 批量写入 —— 已测量否决**
  - 结论与数据见"报告 §4"

## P2（已完成）

- [x] **P2-A 扫描器前置过滤，去掉每次扫码的固定无效查询**
  - `_scan_location`：作业类型未开 `barcode_scan_source_location` 时直接 `return False`（省 1 条 `stock.location`）
  - `_scan_dest_location`：未开 `barcode_scan_dest_location` 时直接 `return False`（省 1 条）
  - `_scan_picking`：原 `search` + `search_count` 合并为一次 `search`，Python 侧区分 active/inactive，保留"单据不活跃"的明确报错（省 1 条）
  - `_scan_product`：**不做前置跳过**（否决）。跳过会让"扫另一个产品条码切换产品"失效，也会丢掉"产品不属于本单据"的精确报错；收益不抵体验损失
- [x] **P2-B quant 查询合并**
  - `_compute_qty_available` 改为返回本次读取的 quant 记录集；串号确认路径把该记录集传给 `action_confirm(..., lot_quants=...)` → `_get_serial_pick_error`，不再二次查询同一批 quant（省 1 条）
  - `_scan_lot` / `_resolve_lot_owner` 两处调用点均已透传
  - `_get_serial_pick_error` 的 domain 保持 `product_id + lot_id`，`quantity > 0` 与"客户库位/在库位置"判断仍按原语义在 Python 侧过滤（未改变校验行为）

## P3

- [x] **P3-A** `_process_stock_move_line` 复用 `moves.move_line_ids`（一行 `all_lines`，`other_lines` 用集合差）
  - 结论：**无查询收益**（`mapped()` 与字段读取共用同一次预取，本身就会缓存），仅去掉三处重复调用，属可读性清理；零风险，保留
- [x] **P3-C 前端扫码队列**
  - 位置：`stock_barcodes_picking/static/src/picking_scan_app.esm.js`、`stock_barcodes_mrp/static/src/mrp_scan_app.esm.js`
  - 问题：`if (!barcode || this.state.scanning) return` —— RPC 在飞时到达的条码被**静默丢弃**，高速扫码枪/相机连扫会掉码
  - 方案：`_onScan(barcode)` 只负责入队并触发单 worker 顺序出队（`_scanQueue` + `while` 循环）；原扫码逻辑改名为 `_scanOne(barcode)`，仍是每次扫码 1 次 RPC，未改变时序语义（前一条处理完才处理下一条）
  - 附带收益：不再需要"扫太快就重扫"，操作员侧感知的失败率下降
- [ ] **P3-B** 大单据状态回传（`since`/`version` 增量 + 分页/虚拟滚动）—— **暂不做**
  - 理由：P1-B 后 `get_scan_state` 查询数已与 move 数解耦（1000 行仍 16 条 / ~30 ms）；剩余成本主要在 JSON payload 与前端渲染，需要前后端协议版本化 + 额外回归，收益只在 ≥500 行单据上体现。若有实际大单据客户再启动
- [ ] **P3-D** 校验前预热 `move_ids` / `move_line_ids` —— **不做**
  - 理由：500 行 `button_validate` 实测 3066 查询 / 2.2 s，逐行 create/write quant 与 move line 发生在核心 `stock` 模块，本模块预热只能省个位数查询（<1%），属噪声

## 不做

- `_compute_totals` 不加 `store=True`（TransientModel 无收益）
- 不把 `get_scan_state` 拆成两个 RPC（现状已是 1 次往返）
- 不为 `stock.lot.name` 额外建索引（核心已是 trigram；SN 库到千万级再评估）

## 非性能项

### 已完成：MRP 未选产品直接扫组件 SN（T7）

原行为：`_scan_lot` 在 `product_id` / `active_move_id` 都为空时直接返回 False，未知码被当成品 SN → 报 “Barcode not found”。

现行为（`_scan_lot_without_product`）：
1. 按名称全局查 `stock.lot`（公司域 `[当前公司, False]`）；0 条 → 返回 False，**继续走新成品 SN 流程**（行为不变）
2. 1 条 → `_resolve_lot_owner`：属于本 MO 组件则绑定产品+批次；串号自动消耗 1 个（qty=1）；批次类进入 step=4 数量输入
3. >1 条 → 收窄到本 MO 的组件产品；仍不唯一 → `more_match` 提示“先点选组件行再扫”
4. 属于成品 → 提示“请在成品区输入/扫码”；属于无关产品 → error “not part of this MO”
5. 额外：产品在 MO 里只有一个有效 raw move 时，自动 `active_move_id` 高亮该行（`_clean_values` 不清该字段，连续扫码保持选中）

测试：新增 5 条 T7 用例（串号自动消耗 + 行高亮、批次步进、外部产品拒绝、同名歧义与恢复、未知码仍当成品 SN）。
回归：MRP 116 tests、picking 44 tests 全绿（唯一异常仍是未装 Chromium 的 tour `setUpClass`）；pylint 门禁无告警。
成本：仅在原本要报错的路径上多 1 次 `stock.lot` 查询；正常扫码路径零新增。

## 验收方式（后续回归沿用）

1. `pylint-odoo` 门禁（仓库内 `.pylintrc` / `.pylintrc-mandatory`）
2. 临时库全量测试：`stock_barcodes_picking`、`stock_barcodes_mrp`
3. 重跑同一套测量脚本，对比上面基线表（记录改动后的查询数与耗时）
