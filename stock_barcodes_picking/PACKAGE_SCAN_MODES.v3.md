# 包裹扫描方案（整包裹出货）— v3

> 模块：`stock_barcodes_picking`
> 目标版本：**19.0.1.2.0**（v1.1.16 升级）
> 日期：2026-11-13（v3）
> 状态：**方案，无代码改动**
> v3 核心变化：用**显式意图按钮**消除「扫包裹」的语义歧义；跨单守卫对齐原生；补拆包动作 + 覆盖分析（P3 手工页取消）

---

## 0. 修订摘要（v1 → v2 → v3）

| 项 | v1 | v2 | v3 |
|---|---|---|---|
| 模式 | 整包裹 / 重新拆包 二态开关 | 删除模式，整包常开 | **删除模式 + 显式意图按钮** |
| 扫包裹语义 | 装包 | 按"本单有无预留行"自动判定（G1 待定） | **默认整包拣货**；点「装包」后才是装包 |
| 拆包 | R1 自动清包 / R2 解锁 | 沿用 `action_unpack_package` | **沿用 + 新增拆包动作/行级改数量（P1/P2）** |
| 超量 | 未定义 | 全有或全无 | 全有或全无（不变） |
| 跨单守卫 | 待定 | 保留 forbid | **策略化，默认 `warn`（对齐原生）** |
| 撤销 | 无 | `action_undo_package_scan` | 不变 |

---

## 1. 现状（代码事实）

| 能力 | 位置 | 现状 |
|---|---|---|
| 分发顺序 | `_process_barcode` L858-901 | picking → location → dest → product → **lot** → **package** |
| 扫包裹 | `_scan_package` L1442 → `_bind_to_package` L1458 | 语义是**装包**（把已拣未装包的行绑到该包） |
| 未知批次 | `_create_new_lot_flow` L1416-1422 | `use_create_lots=False` 时报错并**消费条码** |
| 跨单守卫 | `_get_lot_pick_error` L1726，跨单查询 L1811-1827 | 仅 serial；他单存在未完成行即**直接拒绝** |
| 超量策略 | `barcode_excess_qty_policy`（stock_picking_type L56） | allow / warn / forbid，默认 warn |
| 拆包 | `action_unpack_package` L2492 | 只清 `result_package_id`，**不清 `picked`** |
| 装包校验 | `_lines_need_pack` L808 | mandatory / optional+all_packed 要求已拣行都有包 |
| 现有装包入口 | XML L476-490 + JS | **三个**：`Put in Pack`（新建）、`Select Package`（选已有）、扫包裹号 |
| 现有整包入口 | — | **没有** |

前端关键点：

- `onPutInPack`（js L1051）→ 新建包并装入
- `onSelectPackage`（js L1204）→ 弹窗选已有包 → `action_select_existing_package`（js L1229）
- `canPutInPack`（js L1457）= `show_put_in_pack && picking_id && 存在 quantity>0 且无包的 move`

---

## 2. 方案总览：三个互斥动作

| 动作 | 入口 | 结果 |
|---|---|---|
| **新建包裹** | 按钮「新建包裹」 | 生成新包，装入已拣未装包的行 |
| **装包到已有包裹** | 按钮「装包」→ 扫包裹号；或小按钮「选包」直接弹窗选 | 绑到目标包（`result_package_id`） |
| **整包拣货** | **直接扫包裹号**（不按任何按钮） | 包内本单预留行全部 `picked=True` |

三个动作语义互斥、各有明确入口，**不需要系统猜**。

---

## 3. 显式意图（消除 G1）

### 3.1 设计

扫包裹号的含义由「是否处于装包意图」决定：

```
默认（intent = take）
  扫包裹号 → 整包拣货

点「装包」（intent = pack）
  扫包裹号 → 装包
  点「选包」→ 弹窗选包 → 装包（无需扫）
```

### 3.2 服务端字段（必须在 wizard，不能只放前端）

```python
package_scan_intent = fields.Selection(
    [("take", "整包拣货"), ("pack", "装包")],
    default="take",
    help="Transient one-shot intent: the next package barcode is "
         "interpreted as a pack target instead of a whole-package pick.",
)

def action_set_pack_intent(self):
    self.package_scan_intent = "pack"
```

`get_scan_state()` 暴露 `package_scan_intent`、`has_package_moves`，供前端高亮与提示条。

### 3.3 分流实现

```python
def _scan_package(self, barcode):
    self.ensure_one()
    if not self.picking_id:
        return False
    package = self.env["stock.package"].search([("name", "=", barcode)], limit=1)
    if not package:
        return False
    if self.package_scan_intent == "pack":
        ok = self._bind_to_package(package)      # 现有逻辑
        self.package_scan_intent = "take"        # 一次性，用完复位
        return ok
    return self._process_package_scan(package)   # 新增：整包拣货
```

### 3.4 复位时机

| 时机 | 动作 |
|---|---|
| 装包成功 | 复位为 `take` |
| 装包失败（无可装货） | 复位为 `take`，提示原因 |
| 切换单据 `_switch_picking` | 复位为 `take` |
| 再点一次「装包」 | 复位为 `take`（取消） |
| 扫到产品/批次 | **不复位**（意图保留，等待扫包裹） |

### 3.5 边界情况

| 情况 | 行为 |
|---|---|
| 点了「装包」但扫的是产品 | 产品正常处理，意图保留，提示条继续显示「装包中：扫描目标包裹」 |
| 点了「装包」但无可装货 | 提示「没有可装包的已拣货物」+ 复位 |
| 不按按钮扫包裹，本单无该包预留行 | **明确报错**「该包裹不属于本单；如需装包请点【装包】」——**绝不静默回落成装包** |
| 不按按钮扫包裹，本单无该包且无货 | 同上 |
| 直接点「选包」弹窗选择 | 视为装包，不需要先进意图 |

> 关键原则：**意图只能由用户显式表达，系统不做语义猜测。**

---

## 4. 分发顺序与「未命中不消费」

保持 lot 在 package 之前，只把 lot 扫描器改成未命中返回 `False`：

```python
# _create_new_lot_flow L1416-1422
if not self.picking_id.use_create_lots:
    return False          # 原：_set_message("error", ...) + return True
```

配套：`_process_barcode` 全部扫描器返回 False 后，若「有产品/SN 上下文 且 `use_create_lots=False`」，仍显示原来的
`Serial number/lot %s does not exist. This operation type does not allow creating new ones.`；否则显示 `Barcode not found: %s`。

**残留歧义**：某字符串既是「他产品已存在批次」又是「包裹名」时，lot fallback 会先消费。概率极低，遇到时在消息里补充「该条码也可作为包裹 X 使用」，不自动猜。

---

## 5. 整包拣货：匹配与写入

### 5.1 匹配

```python
lines = env["stock.move.line"].search([
    ("picking_id", "=", picking.id),
    ("state", "not in", ("done", "cancel")),
    ("picked", "=", False),
    "|", ("package_id", "=", pkg.id), ("result_package_id", "=", pkg.id),
])
```

### 5.2 写入（G4）

```python
vals = {"picked": True, "result_package_id": pkg.id}
if not line.package_id:
    vals["package_id"] = pkg.id
elif line.package_id != pkg:
    # 源包与扫描包裹不一致：跳过该行并告警，不覆盖
```

- **不**写 `move.picked`（计算字段，反向写会误标整个 move）
- `quantity` 保持预留值不变
- 一次 `write()` 批量提交
- 源库位校验：`line.location_id` 必须等于扫描源位，不一致则跳过并列入提示

---

## 6. 数量与超量（G2）

**整包 = 全有或全无，绝不部分拣。**

| 情形 | 处理 |
|---|---|
| 包内本单数量 ≤ 剩余需求 | 全拣，数量不变 |
| 超出 且 `allow` | 全拣 + 提示「超拣 N 件」 |
| 超出 且 `warn` | **整包拒绝** → 置 `visible_force_*` 等确认 → 整包执行 |
| 超出 且 `forbid` | **整包拒绝，一行都不改**（校验必须早于任何 write） |

> 需要「只拣一部分」时走 §10 的拆包 / 行级改数量，不在这里做。

---

## 7. 跨单守卫：对齐原生，策略化

### 7.1 原生行为（源码证据）

`stock_move_line._action_done`（`stock/models/stock_move_line.py:699-703`）：

```python
# if this move line is force assigned, unreserve elsewhere if needed
ml._synchronize_quant(-ml.quantity_product_uom, ml.location_id, action="reserved")
```

`:716-719` 在库存不足时调用 `_free_reservation`，后者（`:820-877`）会：

1. 找出**他单**里同产品 + 同批次 + 同库位 + 同包裹、`picked=False` 的行
2. 减少或 `unlink` 它们
3. 重置 `procure_method='make_to_stock'`、清空 `move_orig_ids`
4. 重新 `_action_assign()`

**结论：原生允许第二张单执行，代价是把第一张单的预留抢走**（OUT 退回 `confirmed`/`partially_available`）。

隐藏代价：`_free_reservation` 的搜索域含 `('picked', '=', False)`（`:845`）。若他单那行已 `picked=True`，预留不会被释放 → 数据可能不一致。

### 7.2 策略字段

新增 `barcode_cross_order_policy`（`stock.picking.type`）：

| 取值 | 行为 | 对齐原生 |
|---|---|---|
| `forbid` | 直接拒绝（当前行为） | 比原生严格 |
| **`warn`（建议默认）** | 提示「SN X 已被 WH/OUT/00053 预留，继续将释放其预留」，确认后放行 | 接近原生 + 告知后果 |
| `allow` | 直接放行，消息提示已抢占 | 完全对齐 |

**实现约束**：确认后**不要主动修改他单**，让 `_action_done` 的原生 `_free_reservation` 处理；自行修改会与 core 的重算逻辑冲突。

### 7.3 批量校验

```python
lot_ids = lines.mapped("lot_id").ids
conflicts = env["stock.move.line"].search([
    ("picking_id", "!=", picking.id),
    ("picking_id", "!=", False),
    ("lot_id", "in", lot_ids),
    ("state", "not in", ("done", "cancel")),
])
```

仅 serial 检查；`lot` tracking 允许同批号分给多张单。

---

## 8. 包内非本单货 / 空包 / 混合包（G5）

| 情形 | 处理 | 消息 |
|---|---|---|
| 部分属本单、部分属他单 | **只拣本单**，其余留在包内 | `包裹 X：本单 8 件已拣；另有 2 件属其他单据，未处理` |
| 全部属他单 | 拒绝，不写 | `包裹 X 中没有本单的货物` |
| 本单行已全拣 | 幂等返回 | `包裹 X 已拣完` |
| 包裹不存在 | 不消费，继续后续扫描 | 最终 `Barcode not found` |
| 包裹为空 | 拒绝 | `包裹 X 是空的` |
| 行源库位不符 | 跳过并提示 | `包裹 X：2 件不在源库位，未处理` |

---

## 9. 撤销（G3）

```python
def action_undo_package_scan(self, package_id):
    lines = env["stock.move.line"].search([
        ("picking_id", "=", self.picking_id.id),
        ("state", "not in", ("done", "cancel")),
        ("picked", "=", True),
        "|", ("package_id", "=", package_id), ("result_package_id", "=", package_id),
    ])
    if not lines:
        self._set_message("info", env._("Nothing to undo in this package."))
        return True
    lines.write({"picked": False, "result_package_id": False})
```

交互：同一包裹**再扫一次** → 弹确认 → 撤销（扫码枪连扫常见，必须确认）。

| 动作 | 语义 | 效果 |
|---|---|---|
| `action_unpack_package` | 装好了想换包 | 清 `result_package_id`，`picked` 保留 |
| `action_undo_package_scan` | 扫错了撤掉 | `picked=False` + 清 `result_package_id` |

---

## 10. 拆包动作与场景覆盖分析（P3 已取消）

> 交互原型（工作区 `docs/design/`）：
> - `PACKAGE_SCAN_UI.v3.html` — 主扫码页（显式意图 / 整包拣货 / 行级改数量）
> - `PACKAGE_SPLIT_AND_MANUAL.v3.html` — 拆包动作（P2）+ 手工调拨页（P3，**已取消，仅留档**）

### 10.1 原生事实

原生**没有**"拆包调拨"入口，但有 4 条硬约束：

| 约束 | 位置 |
|---|---|
| `Cannot move an empty package` | `stock_package.py:303` |
| `Packages ... moved to different locations while being in the same container` | `stock_package.py:495` |
| `Can't move a container having packages in another location ...` | `stock_package.py:500` |
| 不同作业类型的货不能混装一包 | `stock_move_line.py:1183` |

另有软信号 `_has_issues()`（`stock_package.py:471`）= 同包各行目的地不一致 → 包裹跨库位。

**所以：原生数据层不禁止部分拣货，但没有配套流程，硬拆会让包裹跨库位。**

### 10.2 方案 A：拆包动作（P2）

先拆再扫，避免包裹跨库位：

```
扫包裹 → 点「拆包」→ 包内明细
  产品 A × 8 → 输入 3
  SN-001     → 勾选
→ 确认 → 生成新包（或散货）
→ 原包保留剩余；新包参与整包拣货
```

```python
def action_split_package(self, package_id, split_data):
    """split_data: [{move_line_id | lot_id, quantity}]"""
    # 1. 新建目标包 / 或 package_id=False
    # 2. stock.quant.move_quants / _update_available_quantity 搬移（库位不变）
    # 3. 更新本单 move line 的 package_id / result_package_id
    # 4. 原包剩余 quant 不动
```

必须在 `stock.quant` 层面搬移，只改 move line 会导致 `_apply_dest_to_package` 容器冲突。

### 10.3 现有行级编辑能力（已实现，不是新功能）

| 方法 | 位置 | 作用 | 限制 |
|---|---|---|---|
| `action_edit_move_line_qty` | L2740 | SET 单条**未装包**已拣行的数量 | serial 拒绝；`qty` 必须 > 0（不能清零） |
| `action_edit_package_qty` | L2807 | SET 某 move 在某包内的已拣行总量 | serial 拒绝；`qty=0` 会 `picked=False` 清行 |

两者都复用 `_get_excess_qty_policy()`，`force` 只放行 warn、不放行 forbid。

**关键结论**：普通批次的部分拣货、清零，现有能力已覆盖；**序列号不可分割**（数量固定 1），
所以"从包里拿掉某个 SN"必须靠拆包动作。

### 10.4 覆盖矩阵：拆包 + 行级编辑是否够

| # | 场景 | 现有能力 | 拆包 | 覆盖 |
|---|---|---|---|---|
| 1 | 整包拣货 | 扫包裹 | — | ✅ |
| 2 | 装包（新建 / 已有） | 新建包裹 / 装包 / 选包 | — | ✅ |
| 3 | 少拣（普通批次） | 行级改数量 | 可选 | ✅ |
| 4 | 少拣（序列号） | ❌ 数量固定 1 | ✅ 勾选拆出 | ✅ 靠拆包 |
| 5 | 从包里拿掉某个 SN | ❌ | ✅ | ✅ 靠拆包 |
| 6 | 普通批次按数量拆 | ⚠️ 可改数量，但包/数量会不一致 | ✅ 精确 | ✅ 拆包更干净 |
| 7 | 超拣 | 行级改数量 + policy | — | ✅ |
| 8 | 扫错撤销 | `action_undo_package_scan` | — | ✅ |
| 9 | 合并两个包 | `unpack` → `装包`（两步） | — | ✅ 组合覆盖 |
| 10 | 一次拆成多个包 | — | ⚠️ 需重复拆 | ⚠️ 可用但繁琐 |
| 11 | 包内混有他单货 | G5 只拣本单 | 需定范围 | ⚠️ 见规则 R3 |
| 12 | 包跨库位（脏数据） | — | ✅ 拆成一致 | ✅ |
| 13 | 逐件任意拣货 | 现有扫码 | — | ✅ |
| 14 | 跨单抢占 | policy `warn` | — | ✅ |

**结论：可以覆盖，P3 手工调拨页不需要做。**

### 10.5 必须定死的 5 条规则

| # | 规则 | 建议 |
|---|---|---|
| R1 | 拆包范围 | **只允许拆本单**（`picking_id = 当前`）的货；包内他单货不可动，提示「另有 N 件属其他单据」 |
| R2 | 拆出后的去向 | 新包裹 / 散货（`package_id=False`）/ 已有包裹，三选一 |
| R3 | 原包被拆空 | 全部拆出时提示「原包将变空」，确认后删除空包（core 不允许空包保留库位） |
| R4 | 已 picked 的行 | 拆包只改包裹结构、**不碰 `picked`**；若该行已 `picked=True`，拆出时自动 `picked=False` 并在消息中说明（避免"拣了但没在包里"的矛盾） |
| R5 | 事务与回滚 | 整个拆包在**一个事务**内完成（quant 搬移 + move line 更新），任一步失败全部回滚 |

### 10.6 优先级（修订）

| 优先级 | 内容 | 理由 |
|---|---|---|
| P0 | 跨单策略 `warn` + 显式意图 | 解除当前阻断 |
| P1 | 现有行级编辑复核（补"改 0"的路径） | 已实现，只需确认 UI 入口 |
| P2 | 拆包动作 | 序列号拆出、包裹数据一致性 |
| ~~P3~~ | ~~手工调拨页~~ | **不做**；接口规则见 R1–R5，未来有跨包批量需求再单独立项 |

---

## 11. UI 与命名

### 11.1 按钮收敛

现状三个装包入口（`Put in Pack` / `Select Package` / 扫包裹）且无整包入口，改为：

| 动作 | 现在 | v3 | 图标 |
|---|---|---|---|
| 新建包并装入 | `Put in Pack` | **新建包裹** | `fa-plus` |
| 进入装包意图 | `Select Package`（名不副实） | **装包** | `fa-inbox` |
| 手动选已有包 | 无 | **选包**（小按钮） | `fa-list` |
| 整包拣货 | 无 | 直接扫包裹（提示条说明） | — |

**英文**：`New Package` / `Pack` / `Choose…`

### 11.2 命名理由

- 「选择包裹」描述的是**手段**（选一个包），不是**意图**（我要装包）；点完其实是去扫包裹，与"选择"不符。
- 「装包」是动词、两字，移动端好点，且与「整包拣货」形成明确对照。
- 「新建包裹」与「装包」区分开，避免两个都叫 pack。

备选：

| 用途 | 推荐 | 可以 | 不建议 |
|---|---|---|---|
| 意图按钮 | **装包** | 装入包裹 / 打包 | 选择包裹、装箱 |
| 小按钮 | **选包** | 选包裹 / 从列表选 | Select Package |

### 11.3 状态与提示条

| 状态 | 按钮 | 提示条 |
|---|---|---|
| 默认 | 「装包」描边 | `扫包裹 = 整包拣货` |
| 装包中 | 「装包中…」实心高亮 | `装包中：扫描目标包裹或点【选包】` + ✕ |

### 11.4 显示条件

- `show_put_in_pack` 为真即显示「装包」（**不再**要求"已有已拣未装包行"，否则"先点装包→再拣货→再扫包"走不通）
- 点击或扫包裹时再校验有无可装货
- 无 `stock.group_tracking_lot` 时三个包裹按钮全部隐藏

### 11.5 移动端

- 「选包」做小、与「装包」拉开间距，防误触
- 意图激活时文字加省略号（「装包中…」）比单纯变色更醒目

---

## 12. 错误提示矩阵

| 场景 | 类型 | 文案要点 |
|---|---|---|
| 包裹不存在 | 静默 → not_found | `Barcode not found: X` |
| 包裹为空 | error | `包裹 X 是空的` |
| 无本单货物（整包意图） | error | `包裹 X 中没有本单的货物；如需装包请点【装包】` |
| 已全部拣完 | info | `包裹 X 已拣完` |
| 超量 forbid | error | `超出剩余需求 N 件，策略禁止超拣` |
| 超量 warn | more_match | `超出剩余需求 N 件，确认后继续` |
| 跨单占用（warn） | more_match | `SN X 已被 WH/OUT/00053 预留，继续将释放其预留` |
| 跨单占用（forbid） | error | `SN X 已被 WH/OUT/00053 预留，禁止拣货` |
| 部分行源位不符 | info | `包裹 X：N 件不在源库位，未处理` |
| 部分行属他单 | info | `包裹 X：本单 N 件已拣；另有 M 件属其他单据` |
| 装包但无可装货 | info | `没有可装包的已拣货物` |

---

## 13. 幂等 / 性能 / 验证联动

- 幂等：重复扫同包且全已拣 → info，不重复加数量
- 性能：整包一次 `write`；跨单守卫一次 `search`；不逐行调 `_get_lot_pick_error`
- 验证：整包后 `_lines_need_pack` 天然满足；回归 `barcode_require_pack="mandatory"` 路径

---

## 14. 待确认决策

| # | 决策 | 结论 | 状态 |
|---|---|---|---|
| D-A | 默认跨单策略 | **`warn`**（对齐原生 + 告知后果，确认后放行） | ✅ 已定（2026-11-13） |
| D-B | 拆包先做哪项 | **P1 行级改数量**（成本最低，先让操作员能"少发几件"） | ✅ 已定（2026-11-13） |
| D-C | 手工调拨页是否现在做 | **不做**：拆包 + 现有行级编辑已覆盖（矩阵见 §10.4）；P3 原型仅留档 | ✅ 已定（2026-11-13 复评） |
| D-D | 是否加过渡开关 `barcode_package_scan_default` | 不加 | 已定 |
| D-E | 提示条默认文案 | `扫包裹 = 整包拣货` | 已定 |
| D-F | 撤销交互 | 重扫同包 + 确认 | 已定 |

> **D-C 复评结论**：原 P3「手工扫码调拨页」的能力已被 `action_edit_move_line_qty` / `action_edit_package_qty`
> 与拆包动作组合覆盖（§10.4 矩阵 14 个场景），**不再单独立项**。接口规则沉淀为 §10.5 的 R1–R5，
> 未来若出现"跨包批量操作"再立项。原型 `docs/design/PACKAGE_SPLIT_AND_MANUAL.v3.html` 保留作历史参考。

---

## 15. 实施顺序

1. **阶段一**：`package_scan_intent` 字段 + 「装包/选包/新建包裹」按钮 + `_scan_package` 分流 + 意图复位
2. **阶段二**：`_process_package_scan` 整包写入 + 超量校验 + 批量跨单检查 + 未命中不消费
3. **阶段三**：`action_undo_package_scan` + 前端重扫确认
4. **阶段四**：行级改数量复核（补"改 0"路径的 UI 入口）→ 拆包动作（按 R1–R5）
5. **阶段五**：`get_scan_state` 增加 `has_package_moves` / `package_scan_hint`；RULES.md 补 1.1.6 例外；版本号 → `19.0.1.2.0`

> ~~P3 手工调拨页~~ 已取消（见 §10.4 / §14 D-C）。

---

## 16. 测试清单

| # | 用例 | 断言 |
|---|---|---|
| 1 | 直接扫包裹 | 整包拣货，不装包 |
| 2 | 点「装包」→ 扫包裹 | 装包，意图复位 |
| 3 | 点「装包」→ 扫产品 | 意图保留，产品正常 |
| 4 | 点「装包」→ 再点一次 | 取消，回整包语义 |
| 5 | 点「装包」→ 切单 | 意图复位 |
| 6 | 不按按钮扫非本单包 | 报错，不装包 |
| 7 | 「装包」但无可装货 | 提示 + 复位 |
| 8 | 「选包」直接选 | 装包成功 |
| 9 | 刷新页面 | 意图不丢失 |
| 10 | 整包：部分行已拣 | 只改未拣行 |
| 11 | 重复扫同包 | 幂等 |
| 12 | 超量 allow / warn / forbid | 全拣 / 确认 / 一行不改 |
| 13 | 跨单占用 warn | 提示后可继续 |
| 14 | 跨单占用 forbid | 拒绝 |
| 15 | 包内非本单货 | 只拣本单 |
| 16 | 空包 | 拒绝 |
| 17 | 撤销 | `picked=False`、清包 |
| 18 | 验证 + backorder | 正常 |
| 19 | 无 `stock.group_tracking_lot` | 按钮隐藏、不触发 |
| 20 | 拆包：勾选 2 个 SN 拆出 | 新包 2 件、原包减 2 件，quant 归属同步 |
| 21 | 拆包：普通批次 5 拆 3 | 新包 3 件、原包 2 件，库位不变 |
| 22 | 拆包：全部拆出 | 提示空包并删除，不残留空包 |
| 23 | 拆包：包内混他单货 | 只拆本单，他单货不动 |
| 24 | 拆包：事务失败 | 全部回滚，quant 与 move line 不变 |
| 25 | 行级编辑：普通批次改 0 | `picked=False`、数量清零 |
| 26 | 行级编辑：serial | 拒绝，提示数量固定 1 |

---

## 17. 明确不做

- 不做常驻模式开关（意图是一次性的）
- 不做「切换意图时清空包裹」的破坏性操作
- 不改原生 `button_validate` / backorder
- 不改 `barcode_require_pack` 语义
- 前端不做业务判断
- 整包扫描不做部分拣（部分拣走 §10）
