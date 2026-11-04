# Stock Barcodes Picking 规则总表

> 模块：`stock_barcodes_picking`  
> 版本基线：`19.0.1.1.1`  
> 当前增量：`19.0.1.1.3`（批号实时已拣与多批号独立累加，见第 21 节）
> 整理日期：2026-11-04  
> 用途：统一现行规则口径、核对实现颗粒度、登记重复或冲突点，供后续开发与回归测试使用。

## 1. 文档口径

1. 本表以**当前代码实际行为**为准，不以 README、字段名称或注释推断行为。
2. 本表是规则审计，不代表所有现行行为都是已确认的理想设计；问题集中列在第 17 节。
3. 规则 ID 是后续变更的稳定锚点。代码行号只对应上述版本，后续修改代码时应保留规则 ID 并更新行号。
4. “已覆盖”表示测试文件中存在直接测试；“部分覆盖”表示只覆盖部分分支；“未见直接测试”不表示功能未运行，只表示本次静态盘点未找到直接测试。
5. 本轮只整理文档，未修改业务代码，也未重新执行完整测试套件。

### 1.1 状态标记

| 标记 | 含义 |
|---|---|
| 现行 | 代码中明确存在的行为。 |
| 确定问题 | 可从代码直接确定的错误、遗漏或矛盾。 |
| 待确认设计 | 当前行为明确，但是否符合业务预期需要决策。 |
| 有意分支 | 看似重复，但分别服务于不同入口或场景，不应简单合并。 |
| 文档偏差 | 注释、字段说明或 README 与代码不完全一致。 |

### 1.2 主要源码索引

| 简称 | 文件 |
|---|---|
| Wizard | [wizard/stock_barcodes_picking.py](wizard/stock_barcodes_picking.py) |
| OWL | [static/src/picking_scan_app.esm.js](static/src/picking_scan_app.esm.js) |
| XML | [static/src/picking_scan_app.xml](static/src/picking_scan_app.xml) |
| Tests | [tests/test_stock_barcodes_picking.py](tests/test_stock_barcodes_picking.py) |

## 2. 颗粒度总览

后续开发必须先确认操作属于哪一层，避免把“当前选中行”“同产品全部行”“整张调拨”混用。

| 层级 | 当前实际颗粒度 | 关键规则 |
|---|---|---|
| 条码分发 | 每次一个条码，按固定顺序串行匹配。 | DSP-002 |
| 扫描上下文 | 当前向导中的 picking、库位、产品、批次、数量。 | CTX-001～CTX-007 |
| 选中行 | `active_move_id` 主要用于产品识别、界面高亮和部分消耗入口。 | CTX-006、QTY-002 |
| 明细匹配 | 同产品全部非取消 move 中，按产品＋源库位＋批次找明细。 | QTY-002、QTY-003 |
| 明细写入 | 匹配时写第一条；新建时写同产品第一条 move。 | QTY-008、QTY-012 |
| 超量需求 | 同产品全部非取消 move 的需求汇总。 | QTY-006 |
| 包装/装箱 | 当前整张 picking 的全部已拣未包装明细，不限当前产品。 | PACK-001～PACK-005 |
| 删除批次/SN | 当前 picking 下指定 move＋lot 的第一条活动明细。 | ACT-001 |
| 总进度/验证 | 整张 picking。 | QTY-017、ACT-003 |

## 3. 配置规则（CFG）

| 规则 ID | 配置/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| CFG-001 | `barcode_scan_source_location` | 默认 `True`。开启时要求扫描源库位；关闭时直接使用 picking 默认源库位。 | [Picking Type:10-16](models/stock_picking_type.py#L10-L16)、[Wizard:252-288](wizard/stock_barcodes_picking.py#L252-L288) | 部分覆盖 |
| CFG-002 | `barcode_scan_dest_location` | 默认 `False`。开启时要求扫描目标库位；关闭时直接使用 picking 默认目标库位。 | [Picking Type:17-24](models/stock_picking_type.py#L17-L24)、[Wizard:278-283](wizard/stock_barcodes_picking.py#L278-L283) | 未见直接测试 |
| CFG-003 | `barcode_show_reserved_sns` | 默认 `True`；只控制预留但未拣批次/SN 的显示，不代表已完成，也不直接改变库存。 | [Picking Type:25-31](models/stock_picking_type.py#L25-L31)、[Wizard:448-517](wizard/stock_barcodes_picking.py#L448-L517) | 未见直接测试 |
| CFG-004 | `barcode_require_pack` | 默认 `no`；选项为 `mandatory`、`optional`、`no`。代码中它参与验证前包装检查，不参与每次产品确认的写入条件。 | [Picking Type:32-43](models/stock_picking_type.py#L32-L43)、[Wizard:587-595](wizard/stock_barcodes_picking.py#L587-L595) | 未见直接测试；口径待对齐 |
| CFG-005 | `barcode_validation_all_packed` | 默认 `False`。仅在 `barcode_require_pack=optional` 时追加“验证前全部已拣明细必须包装”；`mandatory` 无论此字段与否都要求包装。 | [Picking Type:77-83](models/stock_picking_type.py#L77-L83)、[Wizard:587-595](wizard/stock_barcodes_picking.py#L587-L595) | 未见直接测试 |
| CFG-006 | `barcode_excess_qty_policy` | 默认 `warn`。`allow` 直接写入；`warn` 首次拦截并要求 Force Consume；`forbid` 拒绝。无 picking type 时回退 `warn`。 | [Picking Type:44-60](models/stock_picking_type.py#L44-L60)、[Wizard:1553-1563](wizard/stock_barcodes_picking.py#L1553-L1563) | 已覆盖主要分支 |
| CFG-007 | `barcode_new_product_policy` | 默认 `forbid`。只处理“已存在序列号所属产品不在当前单据”的场景，不是通用的产品强制添加开关。 | [Picking Type:61-76](models/stock_picking_type.py#L61-L76)、[Wizard:1099-1105](wizard/stock_barcodes_picking.py#L1099-L1105) | 已覆盖主要分支 |
| CFG-008 | 原生 `picking_type.use_create_lots` | 控制未知批次/SN 是否可按当前产品创建；关闭时未知名称直接报错。 | [Wizard:978-1053](wizard/stock_barcodes_picking.py#L978-L1053) | 部分覆盖 |
| CFG-009 | `barcode.max_time_between_keys_in_ms` | 安装时设为 `1500`；`noupdate=1`，后续升级不覆盖管理员修改。 | [ir_config_parameter.xml:14-19](data/ir_config_parameter.xml#L14-L19) | 安装配置 |
| CFG-010 | 安装/升级回填 | 安装 hook 和 `19.0.1.1.0` migration 都把源库位扫描的 False/NULL 回填为 True，用于保持旧版强制扫源位行为。 | [hooks.py:4-21](hooks.py#L4-L21)、[migration:16-22](migrations/19.0.1.1.0/post-update_fields.py#L16-L22) | 有意分支；覆盖语义见 ISS-020 |
| CFG-011 | 包装按钮权限 | 前端以 `stock.group_tracking_lot` 控制 Pack/Select Package 按钮；原生需要包装类型时还可能打开 `stock.put.in.pack` 向导。 | [Wizard:581-584](wizard/stock_barcodes_picking.py#L581-L584)、[OWL:996-1002](static/src/picking_scan_app.esm.js#L996-L1002) | 未见直接测试 |
| CFG-012 | 配置界面 | 作业类型 Barcode 页签分组为 Location Scanning、Serial Numbers、Quantity Control、Packaging；包装组受同一权限组控制。 | [stock_picking_type_views.xml:13-30](views/stock_picking_type_views.xml#L13-L30) | 界面规则 |

## 4. 入口与单据状态（ENT）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| ENT-001 | Form 的 Barcode Scan | 绑定当前 picking；只在 `assigned`、`confirmed`、`partially_available` 显示。 | [stock_picking_views.xml:9-21](views/stock_picking_views.xml#L9-L21)、[stock_picking.py:9-30](models/stock_picking.py#L9-L30) | 未见直接测试 |
| ENT-002 | List/Kanban 顶部 Scan | 不绑定 picking，进入 scan-first；先扫描调拨单号。 | [stock_picking.py:32-56](models/stock_picking.py#L32-L56)、[stock_picking_views.xml:31-37](views/stock_picking_views.xml#L31-L37) | 部分覆盖 |
| ENT-003 | List/Kanban 行/卡片 Scan | 绑定当前 picking；除 Form 的三种状态外，还允许 `waiting`。 | [stock_picking_views.xml:38-45](views/stock_picking_views.xml#L38-L45)、[stock_picking_views.xml:64-71](views/stock_picking_views.xml#L64-L71) | 状态口径不统一 |
| ENT-004 | 扫描调拨标识 | 按 `stock.picking.name` 精确匹配，不使用独立 barcode 字段。 | [Wizard:719-745](wizard/stock_barcodes_picking.py#L719-L745) | 已覆盖 |
| ENT-005 | 扫到非活动单号 | 只认 `confirmed`、`assigned`、`partially_available` 为可切换状态；若单号存在但都不活动，直接报错，不继续向其他扫描器穿透。 | [Wizard:727-744](wizard/stock_barcodes_picking.py#L727-L744) | 部分覆盖 |
| ENT-006 | 一个活动候选 | 直接切换；若就是当前 picking，仅提示 Already on transfer，不重置上下文。 | [Wizard:758-763](wizard/stock_barcodes_picking.py#L758-L763) | 部分覆盖 |
| ENT-007 | 多个活动候选 | 打开候选列表，保留旧 picking 但不允许继续写入；只能点选候选或再扫一个可唯一确定的单号。 | [Wizard:746-757](wizard/stock_barcodes_picking.py#L746-L757) | 已覆盖 |
| ENT-008 | 候选点选 | 服务端再次验证 ID 必须属于当前候选集，然后执行统一切单。 | [Wizard:408-424](wizard/stock_barcodes_picking.py#L408-L424) | 已覆盖 |
| ENT-009 | `action_confirm` 的单据状态 | 明确拒绝 `draft`、`done`、`cancel`；没有拒绝 `waiting`。 | [Wizard:1429-1441](wizard/stock_barcodes_picking.py#L1429-L1441) | 与 ENT-005 口径不同 |
| ENT-010 | Validate 按钮 | 有 picking 且状态不是 `draft`、`done`、`cancel` 即显示，因此也允许 `waiting`。 | [OWL:973-979](static/src/picking_scan_app.esm.js#L973-L979) | 未见直接测试 |
| ENT-011 | 向导生命周期 | 使用 `TransientModel`，`_transient_max_hours=48`；扫描确认后的 move/move line 是即时业务写入，并非整个会话最后统一提交。 | [Wizard:8-12](wizard/stock_barcodes_picking.py#L8-L12) | 架构规则 |

## 5. 条码入口、分发与步骤（DSP）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| DSP-001 | 硬件/手动输入 | 硬件经 barcode bus；手动输入按 Enter。手动端 `trim()`，旧硬件入口也 `strip()`。 | [OWL:33-45](static/src/picking_scan_app.esm.js#L33-L45)、[OWL:332-343](static/src/picking_scan_app.esm.js#L332-L343)、[Wizard:614-633](wizard/stock_barcodes_picking.py#L614-L633) | 未见直接前端测试 |
| DSP-002 | 普通条码分发 | 固定顺序：picking → 源库位 → 目标库位 → 产品 → 批次/SN → 包装 → not found。 | [Wizard:637-680](wizard/stock_barcodes_picking.py#L637-L680) | 部分覆盖 |
| DSP-003 | 扫描器未匹配 | 返回 False 并继续后续扫描器；已识别但状态不允许的单号属于拦截例外。 | [Wizard:637-644](wizard/stock_barcodes_picking.py#L637-L644) | 已覆盖主要路径 |
| DSP-004 | 候选单选择器打开 | 条码入口只接受 picking 名；其他扫码被拦截。写操作通过共享守卫阻止落入旧 picking。 | [Wizard:647-701](wizard/stock_barcodes_picking.py#L647-L701) | 已覆盖；删除例外见 ISS-008 |
| DSP-005 | 单据外产品待确认 | `visible_force_add=True` 时阻止继续扫码，必须先 Add Product and Pick 或 Cancel。 | [Wizard:658-666](wizard/stock_barcodes_picking.py#L658-L666) | 已覆盖 |
| DSP-006 | 所有扫描器未匹配 | 设置 `message_type=not_found`；OWL 保存该条码并显示 Force add 按钮，但是否能添加仍由服务端重新校验。 | [Wizard:677-680](wizard/stock_barcodes_picking.py#L677-L680)、[OWL:309-315](static/src/picking_scan_app.esm.js#L309-L315) | 部分覆盖 |
| DSP-007 | OWL 扫码 RPC | `process_barcode_and_dispatch` 处理条码后固定返回 `action=None` 和最新 state；弹窗动作来自独立 action RPC，而非该扫码入口。 | [Wizard:703-716](wizard/stock_barcodes_picking.py#L703-L716) | 文档偏差见 ISS-022 |
| DSP-008 | 动态步骤 | 源库位和目标库位按配置加入；之后固定为 product → lot → qty。非跟踪产品在扫描后跳过 lot。 | [Wizard:151-177](wizard/stock_barcodes_picking.py#L151-177)、[Wizard:871-882](wizard/stock_barcodes_picking.py#L871-L882) | 已覆盖 |
| DSP-009 | 步骤约束强度 | 步骤主要起引导作用；产品、批次、库位扫描器没有统一的“必须在当前步骤”限制。 | [Wizard:765-976](wizard/stock_barcodes_picking.py#L765-L976) | 待确认设计 |
| DSP-010 | 初始默认值 | 扫源位开启时清空 `location_id`；关闭时取 picking 源位。目标位扫描关闭时取 picking 目标位。起始 step 为 0。 | [Wizard:252-288](wizard/stock_barcodes_picking.py#L252-L288) | 部分覆盖 |
| DSP-011 | 步骤提示 | `_set_message_step()` 总是写入 `info` 类型的当前步骤提示，并会覆盖此前消息。 | [Wizard:184-219](wizard/stock_barcodes_picking.py#L184-L219) | 消息口径见 ISS-018 |
| DSP-012 | 成功确认后的清理 | 清空产品、批次、数量、可用量及两个确认标志，step 回 product；保留 `active_move_id` 便于连续扫同产品。 | [Wizard:2237-2258](wizard/stock_barcodes_picking.py#L2237-L2258) | 已覆盖 |

## 6. 切单、暂存与选中行（CTX）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| CTX-001 | 切到另一张 picking | 先暂存旧单未确认上下文，再完整重置向导，最后尝试恢复新单快照。 | [Wizard:360-406](wizard/stock_barcodes_picking.py#L360-L406) | 已覆盖 |
| CTX-002 | 暂存条件 | 只有 `product_id` 或 `lot_id` 非空才暂存；仅扫完库位、尚未选产品时不会暂存。 | [Wizard:291-322](wizard/stock_barcodes_picking.py#L291-L322) | 待确认设计 |
| CTX-003 | 暂存内容 | 保存产品、UoM、批次、数量、源/目标位、active move、step、超量及新产品确认标志。 | [Wizard:302-321](wizard/stock_barcodes_picking.py#L302-L321) | 部分覆盖 |
| CTX-004 | 恢复 | 快照按 picking ID 保存，恢复即删除；step 0 合法保留；恢复后重算可用量并刷新步骤提示。 | [Wizard:324-358](wizard/stock_barcodes_picking.py#L324-L358) | 已覆盖 |
| CTX-005 | 切单消息 | 恢复/默认提示之后，再组合为 `Switched to transfer ...`；最终消息包含切单和下一步。 | [Wizard:400-406](wizard/stock_barcodes_picking.py#L400-L406) | 部分覆盖 |
| CTX-006 | 点击产品行 | `set_active_move` 只验证 move 属于当前 picking；设置高亮和后续批次搜索上下文，不等同于锁定实际写入 move。 | [Wizard:2051-2067](wizard/stock_barcodes_picking.py#L2051-L2067) | 已覆盖归属校验；颗粒度见 ISS-003 |
| CTX-007 | active move 切换 | 扫产品或直接识别批次所属产品后，若当前 active move 属于其他产品，则改为该产品第一条非取消 move；同产品连续扫码时保留。 | [Wizard:857-865](wizard/stock_barcodes_picking.py#L857-L865)、[Wizard:1219-1228](wizard/stock_barcodes_picking.py#L1219-L1228) | 已覆盖 |

## 7. 库位规则（LOC）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| LOC-001 | 源库位扫描关闭 | `_scan_location` 直接穿透，不执行库位查询。 | [Wizard:765-770](wizard/stock_barcodes_picking.py#L765-L770) | 部分覆盖 |
| LOC-002 | 扫描源库位 | 按 barcode 查第一条库位；只接受 `usage=internal`，其他 usage 直接报错并消费该条码。 | [Wizard:771-787](wizard/stock_barcodes_picking.py#L771-L787) | 部分覆盖；冲突见 ISS-001 |
| LOC-003 | 源库位扫描成功 | 写入动态 `location_id`，然后 `step += 1`，再显示对应步骤提示。 | [Wizard:788-794](wizard/stock_barcodes_picking.py#L788-L794) | 已覆盖基础路径；边界见 ISS-012 |
| LOC-004 | 目标库位扫描关闭 | `_scan_dest_location` 直接穿透。 | [Wizard:796-808](wizard/stock_barcodes_picking.py#L796-L808) | 未见直接测试 |
| LOC-005 | 扫描目标库位 | 按 barcode 查第一条；采用黑名单，拒绝 `view`、`inventory`、`production`，其他 usage 接受。 | [Wizard:809-822](wizard/stock_barcodes_picking.py#L809-L822) | 未见直接测试；文档偏差见 ISS-022 |
| LOC-006 | 目标库位扫描成功 | 写入 `location_dest_id`，明确跳到 product 步骤。 | [Wizard:823-826](wizard/stock_barcodes_picking.py#L823-L826) | 未见直接测试 |
| LOC-007 | 最终确认 | 无论源位扫描是否开启，`location_id` 都必须存在；目标位扫描开启时，`location_dest_id` 也必须存在。 | [Wizard:1442-1452](wizard/stock_barcodes_picking.py#L1442-L1452) | 源位已覆盖；目标位未见直接测试 |
| LOC-008 | SN 自动确认但无源位 | 最终由 `action_confirm` 报 No source location scanned；不会因为序列号库存校验内部有位置回退而豁免该必填条件。 | [Wizard:911-917](wizard/stock_barcodes_picking.py#L911-L917)、[Wizard:1357-1364](wizard/stock_barcodes_picking.py#L1357-L1364) | 部分覆盖 |

## 8. 产品识别（PRD）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| PRD-001 | 主产品扫描器 | 按 barcode 精确搜索，限制 `type=consu`，不加 `is_storable`，也未显式加 company 条件。 | [Wizard:828-839](wizard/stock_barcodes_picking.py#L828-L839) | 部分覆盖 |
| PRD-002 | 多产品同码 | 返回 `more_match` 的 Multiple products found；没有产品候选选择器。 | [Wizard:840-843](wizard/stock_barcodes_picking.py#L840-L843) | 未见直接测试 |
| PRD-003 | 当前无 picking | 已识别产品时报 No transfer selected，不向后续扫描器穿透。 | [Wizard:844-846](wizard/stock_barcodes_picking.py#L844-L846) | 未见直接测试 |
| PRD-004 | 产品归属 | 产品必须属于当前 picking 的非取消 move；普通产品条码不属于本单时直接报错，不走 CFG-007 的单据外序列号策略。 | [Wizard:847-856](wizard/stock_barcodes_picking.py#L847-L856) | 已覆盖 |
| PRD-005 | 产品识别成功 | 写产品、UoM，清批次，数量默认 1；active move 按 CTX-007 更新。 | [Wizard:857-870](wizard/stock_barcodes_picking.py#L857-L870) | 已覆盖 |
| PRD-006 | 跟踪产品 | 进入 lot 步；最终提示由 `_set_message_step` 生成。 | [Wizard:871-875](wizard/stock_barcodes_picking.py#L871-L875) | 已覆盖 |
| PRD-007 | 非跟踪产品 | 跳过 lot，进入 qty 步；可用默认数量 1 直接 Confirm。 | [Wizard:876-882](wizard/stock_barcodes_picking.py#L876-L882)、[OWL:962-971](static/src/picking_scan_app.esm.js#L962-L971) | 已覆盖 |
| PRD-008 | 批次全局回退中的产品查询 | 在未找到全局 lot 后，再按 barcode＋当前公司/共享公司查产品；这里没有 `type=consu` 限制。 | [Wizard:964-976](wizard/stock_barcodes_picking.py#L964-L976) | 口径见 ISS-015 |

## 9. 批次与序列号识别（LOT）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| LOT-001 | 当前产品下的 lot 查询 | 搜索上下文优先取 `product_id`，否则取 active move 产品；按名称＋产品精确查 lot，未显式按 company 过滤。 | [Wizard:885-905](wizard/stock_barcodes_picking.py#L885-L905) | 已覆盖主要路径 |
| LOT-002 | 无产品或当前产品不跟踪 | 进入全局 lot fallback；唯一已存在 SN 可重新识别并覆盖当前产品上下文。 | [Wizard:885-901](wizard/stock_barcodes_picking.py#L885-L901) | 已覆盖 |
| LOT-003 | 全局 lot fallback | 按名称＋当前公司/共享记录搜索。重名时依次尝试按 active move 产品、当前产品、本单产品集合收窄。 | [Wizard:925-963](wizard/stock_barcodes_picking.py#L925-L963) | 部分覆盖 |
| LOT-004 | 收窄后仍多选 | 提示先点击目标产品行再扫；不显示 lot 候选列表。 | [Wizard:939-961](wizard/stock_barcodes_picking.py#L939-L961) | 未见直接测试 |
| LOT-005 | 唯一已存在 lot/SN | 通过 `_resolve_lot_owner` 判断所属产品是否在本单；本单产品走正常流程，单据外产品按 NEW 规则。 | [Wizard:1208-1279](wizard/stock_barcodes_picking.py#L1208-L1279) | 已覆盖 |
| LOT-006 | 本单已存在 SN | 数量强制为 1，并立即调用 `action_confirm`；成功或失败都消费该条码。 | [Wizard:906-917](wizard/stock_barcodes_picking.py#L906-L917)、[Wizard:1229-1248](wizard/stock_barcodes_picking.py#L1229-L1248) | 已覆盖 |
| LOT-007 | 本单已存在非 SN 批次 | 设置批次并进入 qty 步，不自动确认。 | [Wizard:918-923](wizard/stock_barcodes_picking.py#L918-L923)、[Wizard:1249-1253](wizard/stock_barcodes_picking.py#L1249-L1253) | 部分覆盖 |
| LOT-008 | 未知批次/SN | 先检查原生 `use_create_lots`；不允许创建时直接报不存在且不可创建。 | [Wizard:978-1037](wizard/stock_barcodes_picking.py#L978-L1037) | 已覆盖未知 SN 分支 |
| LOT-009 | 当前产品已足量时再扫未知名称 | 取该产品第一条非取消 move；若已拣量大于等于其需求且超量策略不是 `allow`，清空产品/批次/active move，并要求先扫下一产品。 | [Wizard:990-1020](wizard/stock_barcodes_picking.py#L990-L1020) | 部分覆盖；多 move 口径待确认 |
| LOT-010 | 允许创建且有产品上下文 | 将未知码放到 `lot_name`，清空 `lot_id` 和可用量；SN 数量 1 并自动确认，普通批次进入 qty 步。 | [Wizard:1032-1053](wizard/stock_barcodes_picking.py#L1032-L1053) | 部分覆盖 |
| LOT-011 | 实际创建 lot | search-then-create：先按名称＋产品查找；没有再创建，company 取当前 picking 公司或环境公司。 | [Wizard:1281-1294](wizard/stock_barcodes_picking.py#L1281-L1294) | 已覆盖 |
| LOT-012 | 新 lot 的确认时机 | `action_confirm` 在超量判定和明细写入之前调用 `_create_new_lot`。 | [Wizard:1496-1510](wizard/stock_barcodes_picking.py#L1496-L1510) | 副作用见 ISS-019 |

## 10. 库存、预留、退货与重复 SN（STK）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| STK-001 | 可用量显示 | `qty_available` 汇总 quant 的 `quantity`，不是扣除预留后的 `available_quantity`。无批次时只查精确源库位。 | [Wizard:1296-1324](wizard/stock_barcodes_picking.py#L1296-L1324) | 待确认命名口径 |
| STK-002 | 有批次时可用量 | 为复用 SN 校验会查询该批次全部 quant，但显示值仍只汇总精确等于扫描源位的 quant。 | [Wizard:1303-1315](wizard/stock_barcodes_picking.py#L1303-L1315) | 口径见 ISS-005 |
| STK-003 | SN 实物校验 | 只使用正库存 quant；非 incoming 单若 SN 在 customer 位置，按“已交付”拒绝。 | [Wizard:1326-1333](wizard/stock_barcodes_picking.py#L1326-L1333)、[Wizard:1370-1379](wizard/stock_barcodes_picking.py#L1370-L1379) | 已覆盖 |
| STK-004 | 非 incoming 的源位要求 | SN 必须在扫描源位的 `parent_path` 子树中有正库存，否则报错且不添加。 | [Wizard:1380-1403](wizard/stock_barcodes_picking.py#L1380-L1403) | 已覆盖 |
| STK-005 | 普通供应商收货 | incoming 且无 `return_id` 时，不要求 SN 在 vendor 源位有实物库存；已有 SN 可正常收货。 | [Wizard:1336-1345](wizard/stock_barcodes_picking.py#L1336-L1345)、[Wizard:1366-1385](wizard/stock_barcodes_picking.py#L1366-L1385) | 已覆盖 |
| STK-006 | 客户退货 | `incoming + return_id` 仍需 SN 在 Customers 等实际源位子树中有正库存；源位无货或货在其他位置时扫码即拒绝。 | [Wizard:1366-1403](wizard/stock_barcodes_picking.py#L1366-L1403) | 已覆盖 |
| STK-007 | 新建批次/SN | `action_confirm` 对 `lot_name` 尚待创建的新 lot 跳过整段 `_get_serial_pick_error`，包括实物和跨单占用检查。 | [Wizard:1460-1477](wizard/stock_barcodes_picking.py#L1460-L1477) | 现行规则 |
| STK-008 | 跨调拨占用 | 查询其他 picking 中同产品＋同 lot、状态非 done/cancel 的所有明细；存在即拒绝，不区分 picked，也不显式过滤数量正负。 | [Wizard:1404-1420](wizard/stock_barcodes_picking.py#L1404-L1420) | 已覆盖主要分支；范围见 ISS-016 |
| STK-009 | 校验优先级 | 已存在 SN 的源库存/跨单占用检查先于本单重复 SN 检查，优先报告需要先纠正的真实库存问题。 | [Wizard:1460-1494](wizard/stock_barcodes_picking.py#L1460-L1494) | 已覆盖 |
| STK-010 | 本单重复 SN | 当前 picking 任意 move 上已有 `picked=True` 且同 lot 的明细，就拒绝再次添加。 | [Wizard:1479-1494](wizard/stock_barcodes_picking.py#L1479-L1494) | 已覆盖 |

## 11. 数量、超量与明细写入（QTY）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| QTY-001 | Confirm 基本守卫 | 依次检查候选单已解决、单据状态、产品、源位、按需目标位、跟踪产品批次、正数量。 | [Wizard:1422-1458](wizard/stock_barcodes_picking.py#L1422-L1458) | 已覆盖主要分支 |
| QTY-002 | 目标 move 集合 | 按当前产品收集 picking 中所有 `state != cancel` 的 move；不使用 `active_move_id` 限定。 | [Wizard:1578-1589](wizard/stock_barcodes_picking.py#L1578-L1589) | 颗粒度见 ISS-003 |
| QTY-003 | 匹配明细键 | 在同产品 move 的明细中按产品＋源库位＋批次匹配；不含 active move、目标位或包装。 | [Wizard:1591-1600](wizard/stock_barcodes_picking.py#L1591-L1600) | 部分覆盖；包装维度见 ISS-006 |
| QTY-004 | 收货 SN 占位行 | SN 无精确匹配时，可复用同产品＋源位、无 lot 且未 picked 的第一组占位明细。 | [Wizard:1601-1618](wizard/stock_barcodes_picking.py#L1601-L1618) | 已覆盖收货场景 |
| QTY-005 | 需求占用量 | 其他明细只有 `picked=True` 的数量才计入占用；预填但未拣的收货行不阻挡扫描。 | [Wizard:1619-1627](wizard/stock_barcodes_picking.py#L1619-L1627) | 已覆盖 |
| QTY-006 | 需求上限 | 同产品所有目标 move 的 `product_uom_qty` 汇总；匹配行上限为总需求减其他已拣行数量。 | [Wizard:1623-1635](wizard/stock_barcodes_picking.py#L1623-L1635) | 已覆盖单 move；多 move 未见直接测试 |
| QTY-007 | 匹配行超量 | 非 force 时：`forbid` 直接拒绝；`warn` 设置 `visible_force_done` 并停止；`allow` 继续。 | [Wizard:1631-1653](wizard/stock_barcodes_picking.py#L1631-L1653) | 已覆盖 |
| QTY-008 | 匹配行 SET | 只取 `existing_lines[:1]`，把其 quantity 设为扫描数量并置 picked；数量增加时从其余匹配行扣减，数量减少时不压缩其他匹配行。 | [Wizard:1654-1676](wizard/stock_barcodes_picking.py#L1654-L1676) | 已覆盖基础 SET；多匹配行未见直接测试 |
| QTY-009 | picked 写入 | 创建/更新的明细置 `picked=True`；不直接写整个 `move.picked`，避免原生反向计算把同 move 所有明细都标为已拣。 | [Wizard:1565-1576](wizard/stock_barcodes_picking.py#L1565-L1576)、[Wizard:1666-1676](wizard/stock_barcodes_picking.py#L1666-L1676) | 已覆盖 |
| QTY-010 | 新行超量预检 | 在重分配其他行之前先按策略拒绝或要求确认，避免失败扫描已清空其他行。 | [Wizard:1677-1699](wizard/stock_barcodes_picking.py#L1677-L1699) | 已覆盖 |
| QTY-011 | 新行容量重分配 | 超额时按明细 ID 顺序扣减其他行，归零删除；SN 场景跳过 quantity 大于 0 的其他行。 | [Wizard:1700-1711](wizard/stock_barcodes_picking.py#L1700-L1711) | 部分覆盖 |
| QTY-012 | 新建明细 | 写入同产品 `moves[:1]`；数量取扫描值、picked=True，源位取扫描位，目标位取扫描位或 move 默认位，写 lot/lot_name。 | [Wizard:1712-1731](wizard/stock_barcodes_picking.py#L1712-L1731) | 已覆盖基础路径；多 move 未见直接测试 |
| QTY-013 | Force Consume | 服务端只额外检查超量策略不能是 `forbid`，然后带 `force_create_move=True` 重走 Confirm；不要求 `visible_force_done` 必须先为 True。 | [Wizard:1735-1748](wizard/stock_barcodes_picking.py#L1735-L1748) | 已覆盖正常路径；RPC 前提见 ISS-021 |
| QTY-014 | allow 超量成功消息 | 超量策略为 allow 时，按同产品全部非取消 move 计算已拣减需求，在清理上下文后追加 over demand 提示。 | [Wizard:1510-1551](wizard/stock_barcodes_picking.py#L1510-L1551) | 已覆盖 |
| QTY-015 | Consume by demand | 只允许非跟踪产品；目标为 active move 或该产品第一条活动 move；数量使用该 move 的完整 `product_uom_qty`，不是剩余需求。 | [Wizard:1750-1800](wizard/stock_barcodes_picking.py#L1750-L1800) | 已覆盖 |
| QTY-016 | Consume with qty | 要求 active move、源位和正数量，再委托 Confirm。服务端没有单独禁止 tracked 产品，跟踪要求由 Confirm 的批次守卫处理。 | [Wizard:1802-1830](wizard/stock_barcodes_picking.py#L1802-L1830) | 已覆盖基础路径 |
| QTY-017 | 整单进度 | 需求汇总非 done/cancel move；完成量只汇总这些 move 上 picked 明细。不同产品/UoM 的数值直接相加。 | [Wizard:222-249](wizard/stock_barcodes_picking.py#L222-L249) | 部分覆盖；混合 UoM 见 ISS-017 |
| QTY-018 | 前端数量编辑 | 非 serial 行可编辑，默认填 move 完整需求；Enter 确认、Escape 取消；确认时先 set active move，再调用 consume with qty。 | [OWL:460-540](static/src/picking_scan_app.esm.js#L460-L540)、[XML:163-183](static/src/picking_scan_app.xml#L163-L183) | 未见直接前端测试 |

## 12. 单据外产品与强制添加（NEW）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| NEW-001 | 唯一 SN 属于单据外产品 | 仅当产品 tracking=serial 且策略不是 forbid 时进入新增流程；forbid 直接报错。 | [Wizard:1269-1279](wizard/stock_barcodes_picking.py#L1269-L1279) | 已覆盖 |
| NEW-002 | 进入新增流程 | 唯一 SN 优先于旧扫描上下文：清两个确认标志和 active move，绑定新产品/SN，数量 1。 | [Wizard:1107-1124](wizard/stock_barcodes_picking.py#L1107-L1124) | 已覆盖 |
| NEW-003 | warn | 先执行 SN 安全检查，再只向导向写待确认状态；确认前不创建 move 或 move line。 | [Wizard:1120-1140](wizard/stock_barcodes_picking.py#L1120-L1140) | 已覆盖 |
| NEW-004 | warn 后确认 | 再次验证待确认产品/SN、产品仍不在本单，并通过 `action_confirm` 重查状态、库位、库存和超量，再创建需求 1 的 move 和已拣明细。 | [Wizard:1143-1200](wizard/stock_barcodes_picking.py#L1143-L1200) | 已覆盖 |
| NEW-005 | warn 后取消 | 只清理扫描上下文，不改 picking。 | [Wizard:1202-1206](wizard/stock_barcodes_picking.py#L1202-L1206) | 已覆盖 |
| NEW-006 | allow | 安全校验通过后立即走同一新增确认流程，不显示二次确认。 | [Wizard:1120-1141](wizard/stock_barcodes_picking.py#L1120-L1141) | 已覆盖 |
| NEW-007 | 新 move 创建 | 使用扫描源/目标位，按给定数量创建并 `_action_confirm(merge=False)`，避免与同产品旧 move 合并。 | [Wizard:2069-2090](wizard/stock_barcodes_picking.py#L2069-L2090) | 已覆盖 |
| NEW-008 | `action_force_add` | 独立的非跟踪产品强制添加入口；要求 picking、源位、正数量，按当前数量建 move 并拣货，不读取 CFG-007。 | [Wizard:2092-2145](wizard/stock_barcodes_picking.py#L2092-L2145) | 已覆盖基础路径 |
| NEW-009 | 从未匹配条码强制添加 | 服务端重新按 barcode 查第一条产品，再要求非跟踪、源位和正数量，最后委托 NEW-008。 | [Wizard:2147-2184](wizard/stock_barcodes_picking.py#L2147-L2184) | 已覆盖基础路径；入口闭环见 ISS-007 |
| NEW-010 | 完全未知条码 | 不会自动创建 product/product template；只能由操作员尝试 Force add，且服务端仍要求能解析到已有产品。 | [Wizard:2163-2171](wizard/stock_barcodes_picking.py#L2163-L2171) | 已覆盖 |
| NEW-011 | 强制添加成功消息 | 先 `_clean_values()` 再读取 `self.product_qty` 生成消息。 | [Wizard:2135-2143](wizard/stock_barcodes_picking.py#L2135-L2143) | 确定问题见 ISS-002 |

## 13. 包装规则（PACK）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| PACK-001 | 扫包装名 | 按 `stock.package.name` 查第一条并绑定；找不到则返回 False，但最终分发中包装已是最后一个扫描器。 | [Wizard:1055-1069](wizard/stock_barcodes_picking.py#L1055-L1069) | 未见直接测试 |
| PACK-002 | 扫包装绑定范围 | 重新查询当前 picking 全部非 done/cancel、picked 且未包装明细，不限当前产品或 active move，统一写入目标包装。 | [Wizard:1071-1097](wizard/stock_barcodes_picking.py#L1071-L1097) | 未见直接测试 |
| PACK-003 | Put in Pack | 同样对当前整单全部已拣未包装明细调用原生装箱；可能直接成功，也可能返回包装类型向导。 | [Wizard:1892-1954](wizard/stock_barcodes_picking.py#L1892-L1954) | 未见直接测试 |
| PACK-004 | Select Existing Package | 选择已有包装后，把 `picking_id.move_line_ids` 中全部 picked 且未包装明细绑定到该包装。 | [Wizard:2010-2034](wizard/stock_barcodes_picking.py#L2010-L2034) | 未见直接测试；实现差异见 ISS-009 |
| PACK-005 | 没有已拣未包装明细 | 扫包装、装箱、选已有包装均给出信息提示并返回 True，不创建空包装。 | [Wizard:1084-1097](wizard/stock_barcodes_picking.py#L1084-L1097)、[Wizard:1925-1930](wizard/stock_barcodes_picking.py#L1925-L1930) | 未见直接测试 |
| PACK-006 | Pack 按钮显示 | 有权限且任一后端行 quantity 大于 0 且无 package 时显示；Put in Pack 与 Select Package 使用同一可见条件。 | [OWL:990-1002](static/src/picking_scan_app.esm.js#L990-L1002)、[XML:359-373](static/src/picking_scan_app.xml#L359-L373) | 未见直接前端测试 |
| PACK-007 | 包装重命名 | 前端 trim 且禁止空名；服务端再校验空名和包装存在，然后直接修改该 package.name。 | [Wizard:1956-1974](wizard/stock_barcodes_picking.py#L1956-L1974)、[OWL:675-704](static/src/picking_scan_app.esm.js#L675-L704) | 未见直接测试；范围见 ISS-011 |
| PACK-008 | 拆包 | 只处理当前 picking、指定 package、picked 且活动的明细；传 move_id 时进一步限定该 move。OWL 始终传当前 move 并先浏览器确认。 | [Wizard:1976-2008](wizard/stock_barcodes_picking.py#L1976-L2008)、[OWL:712-745](static/src/picking_scan_app.esm.js#L712-L745) | 未见直接测试 |
| PACK-009 | 选择已有包装的前端入口 | OWL 直接打开 `SelectCreateDialog`，单选且禁止创建；选中后调用 PACK-004。 | [OWL:747-800](static/src/picking_scan_app.esm.js#L747-L800) | 未见直接前端测试 |
| PACK-010 | 后端包装选择 action | `action_open_package_selector` 仍存在并返回 act_window，但当前 OWL 未调用。 | [Wizard:2036-2049](wizard/stock_barcodes_picking.py#L2036-L2049) | 遗留/备用入口，见 ISS-010 |
| PACK-011 | 验证前包装检查 | `mandatory`，或 `optional + barcode_validation_all_packed=True` 时，只要存在 picked 且无 result package 的明细就阻止验证；未 picked 明细不参与此检查。 | [Wizard:1840-1858](wizard/stock_barcodes_picking.py#L1840-L1858) | 未见直接测试 |
| PACK-012 | 包装行显示 | 已拣明细按 result package 分组；未拣预留 SN 只进入未包装组。OWL 再按 move ID 合组，包装行挂在同一产品头下。 | [Wizard:471-539](wizard/stock_barcodes_picking.py#L471-L539)、[OWL:1011-1028](static/src/picking_scan_app.esm.js#L1011-L1028) | 未见直接测试 |

## 14. 删除、验证与 Backorder（ACT）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| ACT-001 | 删除批次/SN | 验证 move 属于当前 picking，搜索该 move＋lot 的活动明细并只取第一条；quantity 大于 1 时减 1，否则删除整条。不会删除 stock.lot 本身。 | [Wizard:2187-2234](wizard/stock_barcodes_picking.py#L2187-L2234) | 未见直接测试；守卫见 ISS-008 |
| ACT-002 | 删除按钮显示 | OWL 只对 picked 批次/SN 显示删除按钮；待拣预留 SN 无删除按钮。 | [XML:253-340](static/src/picking_scan_app.xml#L253-L340) | 前后端范围不同 |
| ACT-003 | Validate | 先检查候选单、picking 和包装，再调用原生 `button_validate()`；返回 dict 时补默认 views 并交给 OWL 打开。 | [Wizard:1832-1871](wizard/stock_barcodes_picking.py#L1832-L1871) | 已覆盖直接验证；包装/向导分支未覆盖 |
| ACT-004 | Backorder | 无论验证直接返回 True 还是打开确认向导，关闭后都尝试切换；只有原 picking 已 done 且存在 backorder 时切到第一张 backorder。 | [Wizard:1873-1890](wizard/stock_barcodes_picking.py#L1873-L1890)、[OWL:802-867](static/src/picking_scan_app.esm.js#L802-L867) | 未见直接 backorder 测试 |

## 15. 前端展示与消息（UI）

| 规则 ID | 触发/前提 | 当前规则 | 源码依据 | 测试/核对状态 |
|---|---|---|---|---|
| UI-001 | 快速连续扫码 | 前端按 FIFO 队列逐条发送 RPC；RPC 进行中不丢弃新条码，也不并发处理。 | [OWL:227-247](static/src/picking_scan_app.esm.js#L227-L247) | 未见直接前端测试 |
| UI-002 | 状态刷新 | 每次扫码/action 后通过后端快照刷新；action 返回值按 False、act_window dict、其他成功值三态处理。 | [OWL:350-410](static/src/picking_scan_app.esm.js#L350-L410) | 未见直接前端测试 |
| UI-003 | 提示音 | `error`、`not_found`、`more_match` 播放错误音；普通 success/info 不播放。 | [OWL:276-281](static/src/picking_scan_app.esm.js#L276-L281) | 未见直接前端测试 |
| UI-004 | 手动输入禁用 | RPC 进行中、候选单待选或单据外产品待确认时禁用手动输入；硬件扫码仍可到后端，由后端守卫拦截。 | [XML:23-29](static/src/picking_scan_app.xml#L23-L29)、[OWL:255-260](static/src/picking_scan_app.esm.js#L255-L260) | 未见直接前端测试 |
| UI-005 | 未匹配条码 | 仅当消息类型为 `not_found` 时记录并展示 Force add；任何其他结果都会清掉该条码。 | [OWL:309-315](static/src/picking_scan_app.esm.js#L309-L315) | 未见直接前端测试 |
| UI-006 | 新扫 SN 高亮 | 对比刷新前后 picked lot，将新扫项移到 pickedLots 末尾并高亮约 2 秒。 | [OWL:261-307](static/src/picking_scan_app.esm.js#L261-L307) | 未见直接前端测试 |
| UI-007 | 产品/包装分组 | 后端一个 move 可返回多个包装行；前端按 move ID 合组并合计 picked 数量，而不是按产品合并多个 move。 | [OWL:1011-1028](static/src/picking_scan_app.esm.js#L1011-L1028) | 未见直接前端测试 |
| UI-008 | 按钮可见性 | Confirm：有 picking、产品、正数量且无新产品待确认；Consume by demand：当前产品非跟踪；Force Consume：由后端标志控制。 | [OWL:962-988](static/src/picking_scan_app.esm.js#L962-L988)、[XML:374-407](static/src/picking_scan_app.xml#L374-L407) | 未见直接前端测试 |
| UI-009 | 消息类型映射 | 前端支持 info、success、warning、error、not_found、more_match 的样式；后端字段 Selection 未定义 warning，现行后端主要使用其余类型。 | [Wizard:89-100](wizard/stock_barcodes_picking.py#L89-L100)、[OWL:949-960](static/src/picking_scan_app.esm.js#L949-L960) | 低优先级口径差异 |
| UI-010 | 成功消息覆盖 | 多处先写具体操作消息，再调用 `_set_message_step()`，最终显示步骤 info；唯一 SN 自动匹配等路径又在步骤提示后重写 success。 | [Wizard:871-883](wizard/stock_barcodes_picking.py#L871-L883)、[Wizard:1233-1248](wizard/stock_barcodes_picking.py#L1233-L1248) | 消息差异见 ISS-018 |

## 16. 安装、视图与辅助规则

| 规则 ID | 当前规则 | 源码依据 |
|---|---|---|
| AUX-001 | 库位表单补充原生 barcode 字段，供源/目标库位扫码使用。 | [stock_location_views.xml](views/stock_location_views.xml) |
| AUX-002 | OWL Back 使用历史返回；另保存进入扫码页前的 session action，以保留列表菜单上下文。 | [OWL:47-77](static/src/picking_scan_app.esm.js#L47-L77)、[OWL:345-348](static/src/picking_scan_app.esm.js#L345-L348) |
| AUX-003 | 后端状态快照排除 done/cancel move；各包装行 quantity 只汇总该行 picked 明细。 | [Wizard:456-539](wizard/stock_barcodes_picking.py#L456-L539) |
| AUX-004 | README 当前只覆盖基础流程和超量策略，不能作为本模块完整规则来源。 | [README.rst](README.rst) |

## 17. 重复、冲突与混乱项清单

### 17.1 优先级说明

- **高**：可阻断正常业务、写错业务对象，或绕过关键守卫。
- **中**：不同入口/层级口径不一致，容易在特定数据条件下产生错误。
- **低**：消息、注释、重复实现或维护成本问题。

| 问题 ID | 级别 | 类型 | 现行情况与影响 | 对齐建议 | 关联规则 |
|---|---|---|---|---|---|
| ISS-001 | 高 | 确定规则冲突 | 源库位扫描只接受 `internal`，但客户退货要求从 `Customers` 源位取货。开启源位扫描时，合法退货源位会被库位扫描器先拒绝。普通供应商收货等非 internal 源位也应一起核对。 | 按 picking 类型/方向定义允许的源位 usage，而不是全局只认 internal；补充“源位扫描开启”的收货和退货测试。 | LOC-002、STK-005、STK-006 |
| ISS-002 | 低 | 确定实现问题 | `action_force_add` 清理数量后才拼成功消息，因此消息中的添加数量会显示 0。 | 清理前保存局部 quantity；只改消息，不改业务数量。 | NEW-011 |
| ISS-003 | 高 | 颗粒度不一致 | UI 的 active move 表示当前选中行，但实际明细匹配、需求汇总和新行落点均按同产品 move 集合处理。同产品多 move 时，选中行不必然是写入行。 | 明确选择“行级写入”或“产品级写入”；若保留产品级，UI 不应暗示选中行是唯一目标。 | CTX-006、QTY-002、QTY-006、QTY-012 |
| ISS-004 | 中 | SET 口径不一致 | 多条明细同时匹配时，只 SET 第一条；增加量会吸收其他匹配行，减少量不会。因此不是该组合总量的统一 SET。 | 明确 SET 是“首行 SET”还是“组合总量 SET”；增加同 lot 多行、分包行测试。 | QTY-008 |
| ISS-005 | 中 | 库位粒度不一致 | SN 实物检查接受源位子树库存，但可用量只统计精确源位；新建明细仍写扫描的父源位，不是实际正库存子位。 | 明确是否允许父位扫描；统一显示量、库存校验和新行库位口径，并覆盖父子库位测试。 | STK-002、STK-004、QTY-012 |
| ISS-006 | 高 | 写入/删除缺包装维度 | 明细匹配不含 result package；删除也只传 move＋lot 并取第一条。同 move、同 lot 跨多个包装时可能更新或删除非预期行。 | 若允许同 lot 分包，行键和 RPC 应带 package/具体 move line；否则明确禁止该数据形态。 | QTY-003、ACT-001、PACK-012 |
| ISS-007 | 中 | 入口前提未闭环 | 所有 `not_found` 都显示 Force add，但服务端要求可解析的已有非跟踪产品、源位和已有正数量。`not_found` 本身不保证这些条件，尤其数量可能已为 0。 | 只在满足前提时显示按钮，或提供明确的数量输入/错误引导；不要将所有 not found 等同于可强制添加。 | DSP-006、NEW-009、NEW-010 |
| ISS-008 | 高 | 服务端守卫遗漏 | `action_remove_move_lot` 未调用候选单共享守卫，也未限制 picked=True。候选单打开时直接 RPC 仍可能改旧 picking；后端能力比 UI 更宽。 | 补共享守卫、明确 picked 限制，并按需要传具体明细/包装。 | DSP-004、ACT-001、ACT-002 |
| ISS-009 | 中 | 近似重复实现 | 扫包装用 fresh search 找已拣未包装行，选已有包装用 picking 关联缓存集合；业务目标相同，读取口径不同。 | 统一为一个内部绑定方法，保留不同入口；补两条入口等价测试。 | PACK-002、PACK-004 |
| ISS-010 | 低 | 备用/遗留双入口 | 后端保留 `action_open_package_selector`，当前 OWL 直接创建 SelectCreateDialog，不会执行该后端 action。 | 标明保留原因；若确认无其他调用方再清理，避免误以为两条路径都会执行。 | PACK-009、PACK-010 |
| ISS-011 | 高 | 对象范围守卫不一致 | 拆包限定当前 picking，重命名包装却只检查 package 存在。直接 RPC 可传入不属于当前 picking 的包装 ID。 | 重命名前验证包装与当前 picking 的已拣明细有关，或明确这是全局包装管理入口。 | PACK-007、PACK-008 |
| ISS-012 | 中 | 步骤推进不对称 | 源位扫描使用 `step += 1`，目标位明确跳 product。非源位步骤再次扫源位时，结果依赖当前索引，可能跳到非预期步骤或越界。 | 源位成功后也按配置明确跳下一步；补重复扫源位和 qty/lot 步扫源位测试。 | LOC-003、LOC-006、DSP-009 |
| ISS-013 | 中 | 入口状态不统一 | Form 和 scan-first 不允许 waiting，List/Kanban 行按钮、Confirm、Validate 却允许 waiting。 | 统一可扫描状态集合；若 waiting 是合法状态，应补 scan-first 和 Form，否则收紧其余入口。 | ENT-001～ENT-010 |
| ISS-014 | 中 | 重复条码处理不统一 | picking 多候选有选择器；产品/lot 多重匹配只提示；库位和包装直接取 limit=1 第一条。 | 制定统一的“一码多对象”策略，至少避免静默取第一条。 | ENT-007、PRD-002、LOT-004、LOC-002、PACK-001 |
| ISS-015 | 中 | 公司与产品查询口径不统一 | 主产品查询限 consu 但不限公司；fallback 产品查询限公司但不限 consu；当前产品 lot 查询不限公司，全局 lot fallback 限公司。 | 明确多公司及共享主数据规则，统一 domain，并补跨公司重复条码测试。 | PRD-001、PRD-008、LOT-001、LOT-003 |
| ISS-016 | 中 | “预留”实际范围更宽 | 跨单 SN 检查命中其他活动调拨的所有同 lot 明细，不看 picked 和正数量；提示统称 reserved。 | 确认业务上要拦截“预留”还是“任何活动明细占用”；按决定补 domain 和测试。 | STK-008 |
| ISS-017 | 中 | 汇总单位/状态口径 | 总需求和超量需求直接汇总 `product_uom_qty`，未做 UoM 转换；写入 move 仅排除 cancel，而展示和总进度排除 done+cancel。 | 明确同产品多 UoM 是否支持；统一活动 move 状态过滤。 | QTY-002、QTY-006、QTY-017、AUX-003 |
| ISS-018 | 低 | 消息重复与覆盖 | 多个扫描器先设置业务消息，随后步骤提示覆盖；不同成功路径最终可能分别显示 info 或 success。 | 规定“先步骤提示、后业务结果”的统一顺序，并为关键路径固定最终消息类型。 | DSP-011、UI-010 |
| ISS-019 | 中 | 拒绝后的副作用 | 新 lot 在超量判定前创建。若后续超量 forbid/warn 返回 False， picking 明细未写，但 stock.lot 可能已保留。 | 明确是否允许“拒绝拣货仍保留主数据”；若不允许，将创建延后到所有拒绝分支之后。 | LOT-012、QTY-007、QTY-010 |
| ISS-020 | 中 | 配置覆盖语义 | 安装 hook 与 migration 是安装/升级两条必要路径，但 migration 会把管理员显式 False 也改 True，不只处理历史 NULL。 | 保留两条生命周期路径；升级时区分历史 NULL 与显式 False，避免覆盖配置。 | CFG-010 |
| ISS-021 | 中 | RPC 与 UI 前提不同 | Force Consume 不要求先存在 `visible_force_done`；直接 RPC 可在 allow/warn 下强制走超量。Consume by demand 明确禁止 tracked，而 Consume with qty 依赖通用批次守卫。 | 明确各 action 的服务端前置条件，不能只依赖按钮可见性。 | QTY-013、QTY-015、QTY-016 |
| ISS-022 | 低 | 注释/文档偏差 | 多处注释仍称多候选未实现、扫码 RPC 可返回候选/backorder、目标位采用白名单、默认函数不设源位等，与代码不一致；JS/XML 也称 outgoing-only。 | 规则行为对齐后同步注释和 README；不要让旧注释继续充当规则来源。 | DSP-007、LOC-005、CTX-001、AUX-004 |
| ISS-023 | 中 | 包装配置名称与执行点不一致 | `mandatory` 的文案是 After Each Product，但代码没有逐产品确认时装箱守卫，实际只在整单验证前检查。 | 决定真实需求是“每个产品后强制”还是“验证前全部包装”；同步字段文案和确认逻辑。 | CFG-004、PACK-011 |
| ISS-024 | 中 | 暂存范围不完整 | 仅扫完库位但未选产品时切单不暂存；恢复又直接使用旧 step，不重算配置变化后的步骤。 | 明确暂存是否应覆盖库位-only 进度；恢复时校验 picking type 配置是否变化。 | CTX-002～CTX-004 |
| ISS-025 | 低 | 可用量命名易误解 | 字段名为 Available，但实际显示 quant.quantity，不扣预留；与跨单占用守卫是两套口径。 | 明确展示“现存”还是“可用”；若保留现口径，调整标签/说明。 | STK-001、STK-008 |

### 17.2 不应误判为“重复”的实现

| 项目 | 为什么需要保留区分 |
|---|---|
| 普通供应商收货 vs 客户退货 | 两者都是 incoming，但供应商收货不要求 vendor 位有 SN 实物；客户退货必须验证实际源位。 |
| 新产品 warn 预览 vs Confirm 正式写入 | 预览只改向导，确认时才创建 move/line，是有意的两阶段确认。 |
| 安装 hook vs migration | 分别覆盖新安装和既有安装升级，不应只按代码相似删除。 |
| Put in Pack vs Select Existing Package | 一个走原生新建包装，一个绑定已有包装，是不同业务入口。 |
| 主产品扫描 vs lot fallback 产品搜索 | 后者承担“条码在常规分发中未被识别后的所有者解析”，但两者 domain 仍需按 ISS-015 对齐。 |

## 18. 测试覆盖矩阵

当前测试文件静态盘点有 **59 个 `test_*` 方法**。以下只登记覆盖关系，不代表本轮重新执行。

| 规则域 | 已有直接测试 | 主要缺口 |
|---|---|---|
| SET、picked、超量 | [Tests:183-418](tests/test_stock_barcodes_picking.py#L183-L418)：SET、双写、allow/warn/forbid、强制超量、额外 SN。 | 多匹配行减少数量、多 move 同产品、混合 UoM。 |
| 源位与切单 | [Tests:419-568](tests/test_stock_barcodes_picking.py#L419-L568)：无源位、切单清位、多候选、候选写入守卫。 | 目标位扫描、waiting 状态、库位-only 暂存、删除动作候选守卫。 |
| 步骤与批次流 | [Tests:569-679](tests/test_stock_barcodes_picking.py#L569-L679)：跟踪/非跟踪步骤、源位推进、完整批次、新 lot 创建。 | 非当前步骤重复扫库位、目标位、跨公司重名。 |
| 消耗与 active move | [Tests:708-850](tests/test_stock_barcodes_picking.py#L708-L850)：按需求/指定数量、外部 move、SN 保持 active、切换产品。 | active move 与实际写入 move 不同的同产品多 move 场景。 |
| SN 库位、退货、占用、重复 | [Tests:851-1015](tests/test_stock_barcodes_picking.py#L851-L1015)：错位、已交付、客户退货、供应商收货、跨单预留、重复 SN。 | 开启源位扫描后扫 Customers/Vendor；父子库位；零数量/未 picked 跨单明细。 |
| 自动识别与未知 SN | [Tests:1016-1086](tests/test_stock_barcodes_picking.py#L1016-L1086)：无产品自动匹配、跨产品 SN、未知 SN。 | 多 lot 收窄仍歧义、产品/包装/库位重复条码。 |
| 单据外产品 SN 策略 | [Tests:1087-1334](tests/test_stock_barcodes_picking.py#L1087-L1334)：allow/warn/forbid、零写入、取消、确认重查、上下文覆盖、后续超量。 | 多公司、不同产品类型、并发重复创建。 |
| Force add | [Tests:1335-1404](tests/test_stock_barcodes_picking.py#L1335-L1404)：创建并拣货、拒绝 tracked、从条码添加、未知条码。 | 成功消息数量、数量上下文为 0 的完整 UI 路径。 |
| 暂存与验证 | [Tests:1405-1440](tests/test_stock_barcodes_picking.py#L1405-L1440)：切回恢复、完整消耗后验证。 | backorder 两种返回、包装向导、配置变化后的恢复。 |
| 包装 | 未见直接测试方法。 | 扫包、选包、装箱、重命名、拆包、mandatory/optional 验证、共享包装、多产品整单绑定。 |
| 删除批次/SN | 未见直接测试方法。 | picked/unpicked、多行同 lot、分包、数量递减、候选单守卫。 |
| OWL 交互 | 未见独立前端测试。 | 扫码队列、按钮可见性、数量编辑、消息覆盖、 Force add 前提。 |

## 19. 后续变更核对模板

每次修改扫码规则时，建议按下面格式补充或更新，不要只改代码而不更新本表：

```text
规则 ID：
变更类型：新增 / 修改 / 删除 / 仅修复实现
触发入口：硬件扫码 / 手动扫码 / 行点击 / action RPC / 验证
作用单据：incoming / outgoing / internal / customer return / 全部
作用颗粒度：条码 / 向导上下文 / move / move line / package / picking
前置条件：
允许状态：
匹配键与排序：
写入对象与字段：
拒绝时是否零业务写入：
最终消息类型与内容：
候选单/新产品/超量/包装守卫：
关联规则及优先级：
测试方法与场景：
RULES.md 是否同步：
```

### 建议优先统一的决策顺序

1. 先确定源库位 usage 与父子库位规则，解决收货/退货阻断。
2. 再确定同产品多 move、同 lot 多明细/多包装的写入与删除颗粒度。
3. 统一可扫描状态、活动 move 状态和候选单写守卫。
4. 明确包装是“逐产品强制”还是“验证前强制”。
5. 最后统一消息、注释、备用入口和测试命名，避免维护口径继续分叉。

## 20. `19.0.1.1.2` 批号待确认数量增量

本节是对 `19.0.1.1.1` 审计基线的增量说明；第 1～19 节保留原基线，便于核对变更前后的规则。本次只调整普通批号的待确认数量与提示，序列号自动确认逻辑不变。

### 20.1 现行规则覆盖

| 基线规则 | `19.0.1.1.2` 现行规则 | 源码依据 |
|---|---|---|
| LOT-007 | 本单已存在普通批次：第一次扫描默认待确认数量为 1；同一批次在未 Confirm 且仍处于 qty 步时连续扫描，数量按 `1→2→…→n` 累加；不自动确认。换批次或 Confirm 清理上下文后重新从 1 开始。 | [Wizard:906-936](wizard/stock_barcodes_picking.py#L906-L936) |
| LOT-010 | 允许创建且有产品上下文：未知普通批次仍只写入 `lot_name`，第一次扫描默认数量为 1；同一新批次未 Confirm 前连续扫描累加到 n。Confirm 前不创建 `stock.lot`，Confirm 时才创建并写入业务明细。 | [Wizard:1051-1081](wizard/stock_barcodes_picking.py#L1051-L1081)、[Wizard:1525](wizard/stock_barcodes_picking.py#L1525) |
| LOT-006、LOT-010（SN 分支） | 已存在或新建的 SN 仍固定数量 1 并自动确认，不应用普通批次的待确认累加规则。 | [Wizard:914-920](wizard/stock_barcodes_picking.py#L914-L920)、[Wizard:1059-1065](wizard/stock_barcodes_picking.py#L1059-L1065) |

### 20.2 手工数量与提示

- 默认数量 1 仍可手工改为其他正数，例如 20，再通过 `action_consume_with_qty` 确认。
- 普通批次提示在 `_set_message_step()` 之后设置，避免被通用步骤提示覆盖；最终消息明确显示批号、当前待确认数量，以及“再次扫描加 1 或 Confirm”。
- Confirm 的前端正数量条件未修改；默认数量为 1 后，扫描普通批次即可显示 Confirm。

### 20.3 新增回归测试

| 测试方法 | 覆盖场景 | 源码依据 |
|---|---|---|
| `test_new_lot_from_active_move_scans_accumulate_before_confirm` | 点击产品行后连续扫新批次 3 次得到 1、2、3；Confirm 前不创建批次；Confirm 后明细数量为 3；再次扫描重新从 1 开始。 | [Tests:646-685](tests/test_stock_barcodes_picking.py#L646-L685) |
| `test_new_lot_default_qty_can_be_edited_before_confirm` | 新批次默认数量 1，可手工改为 20 后确认。 | [Tests:687-700](tests/test_stock_barcodes_picking.py#L687-L700) |
| `test_existing_lot_from_active_move_scans_accumulate` | 已存在批次连续扫描两次得到数量 2，Confirm 后写入已拣明细。 | [Tests:702-717](tests/test_stock_barcodes_picking.py#L702-L717) |

第 18 节的 **59 个测试方法**仍是 `19.0.1.1.1` 静态审计基线。本次新增以上 3 个测试；隔离测试日志统计 `stock_barcodes_picking` 共执行 **64 个测试**，无 `FAIL` 或 `ERROR`。

> 历史说明：第 20 节记录的是 `19.0.1.1.2` 的“待确认数量”规则；`19.0.1.1.3` 已按新的业务要求改为每次扫码立即写入已拣，现行行为以第 21 节为准。

## 21. `19.0.1.1.3` 批号实时已拣与多批号独立累加

### 21.1 现行规则覆盖

| 基线/增量规则 | 现行规则 | 源码依据 |
|---|---|---|
| LOT-007、第 20 节 | 已存在普通批号每次扫描都立即调用确认写入，不再等待手工 Confirm。目标数量是该产品、该源库位、该批号当前已拣数量加 1，再按既有 SET 语义写入，因此连续扫描得到 1、2、…、n。 | [Wizard:905-919](wizard/stock_barcodes_picking.py#L905-L919)、[Wizard:1414-1447](wizard/stock_barcodes_picking.py#L1414-L1447) |
| LOT-010、第 20 节 | 新普通批号第一次扫描就创建 `stock.lot`，并立即写入数量 1 的已拣明细；后续扫描按已存在批号继续累加。 | [Wizard:1034-1045](wizard/stock_barcodes_picking.py#L1034-L1045)、[Wizard:1414-1447](wizard/stock_barcodes_picking.py#L1414-L1447) |
| LOT-005、LOT-007 | 未先选产品时，全局批号回退识别出本单产品后，同样立即已拣并累加，不再停留在 qty 步等待 Confirm。 | [Wizard:1236-1242](wizard/stock_barcodes_picking.py#L1236-L1242) |
| QTY-002、QTY-003 | 同一产品的不同批号分别使用各自已拣明细和数量；交叉扫描 A、B、A 时，只增加本次扫描批号，另一批号数量不变。 | [Wizard:1422-1435](wizard/stock_barcodes_picking.py#L1422-L1435)、[Wizard:1590-1758](wizard/stock_barcodes_picking.py#L1590-L1758) |
| LOT-006、LOT-010（SN 分支） | 序列号仍固定数量 1 并自动确认，重复 SN 校验不变；非跟踪产品的手工数量确认也不受本次修改影响。 | [Wizard:911-917](wizard/stock_barcodes_picking.py#L911-L917)、[Wizard:1037-1043](wizard/stock_barcodes_picking.py#L1037-L1043) |

### 21.2 消息与后续扫描

- 每次成功写入后显示“批号 + 已拣数量 + 再次扫描加 1”。
- 成功后仍按既有 `_clean_values()` 清理本次产品/批号输入，但保留 `active_move_id`，因此可以继续扫同产品的下一批号，不需要重新点击产品行。
- 超量 `allow/warn/forbid`、源库位、单据状态等既有服务端校验仍由 `action_confirm()` 和 `_process_stock_move_line()` 执行。

### 21.3 回归测试

| 测试方法 | 覆盖场景 | 源码依据 |
|---|---|---|
| `test_new_lot_from_active_move_scans_accumulate_immediately` | 新批号每次扫描立即创建/更新已拣明细，连续三次得到 1、2、3。 | [Tests:638-660](tests/test_stock_barcodes_picking.py#L638-L660) |
| `test_multiple_lots_scans_accumulate_independently` | 同产品按 A、B、A、B、A 交叉扫描，最终 A=3、B=2，总已拣为 5。 | [Tests:662-682](tests/test_stock_barcodes_picking.py#L662-L682) |
| `test_existing_lot_without_product_scan_accumulates` | 未选产品时通过全局批号回退立即已拣，第二次扫描继续累加。 | [Tests:684-696](tests/test_stock_barcodes_picking.py#L684-L696) |
| `test_tracked_lot_full_flow`、`test_create_new_lot_search_then_create` | 更新原完整流程和唯一性测试，验证首次扫描即创建并已拣、再次扫描复用批号且数量加 1。 | [Tests:616-636](tests/test_stock_barcodes_picking.py#L616-L636)、[Tests:700-726](tests/test_stock_barcodes_picking.py#L700-L726) |

隔离测试统计 `stock_barcodes_picking` 共执行 **64 个测试**，无 `FAIL` 或 `ERROR`。
