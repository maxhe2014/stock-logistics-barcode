# 包裹扫描方案（整包裹出货）— 修订版 v2

> 模块：`stock_barcodes_picking`（19.0.1.1.16）
> 日期：2026-11-13（v2 修订）
> 状态：**方案，无代码改动**
> 变更：v1 的「二态开关 + 拆包模式」已废弃；改为「整包扫描常开 + 行级拆包 + 撤销动作」

---

## 0. 修订摘要（v1 → v2）

| 项 | v1 | v2 |
|---|---|---|
| 模式开关 | 整包裹 / 重新拆包 二态切换 | **删除**，整包扫描常开 |
| 拆包 | R1 自动清包 / R2 解锁扫描 | **删除模式**，沿用 `action_unpack_package` |
| 超量 | 未定义清楚 | **整包全有或全无**，`allow` 才允许超量 |
| 误扫撤销 | 无 | **新增** `action_undo_package_scan` + 重扫确认 |
| 包内非本单货 | D8 待定 | **只拣本单，其余留在包内并提示** |
| 跨单守卫 | D5 待定 | **保留（serial）**，批量查询 + 可操作提示 |

---

## 1. 现状

### 1.1 代码事实

| 能力 | 位置 | 现状 |
|---|---|---|
| 分发顺序 | `_process_barcode` L858-901 | picking → location → dest → product → **lot** → **package** |
| 扫包裹 | `_scan_package` L1442 / `_bind_to_package` L1458 | 语义是**装包**：把「已拣未装包」的行绑到该包裹 |
| 未知批次 | `_create_new_lot_flow` L1416-1422 | `use_create_lots=False` 时报错并**消费条码** |
| 跨单守卫 | `_get_lot_pick_error` L1811-1827 | **仅 serial**；同 lot 在他单存在未完成行即拒绝 |
| 超量策略 | `barcode_excess_qty_policy`（stock_picking_type L56） | allow / warn / forbid，默认 warn |
| 拆包 | `action_unpack_package` L2492 | 只清 `result_package_id`，**不清 `picked`** |
| 装包校验 | `_lines_need_pack` L808 | mandatory / optional+all_packed 时要求已拣行都有包 |

### 1.2 关键结论

- 「已装包 + 未拣」的行（如 `WH/INT/00001` 的 10 行）**当前无法被扫描命中**：`_process_stock_move_line` 的 `existing_lines` 排除了 `result_package_id` 非空的行（L2046-2052）。
- 因此「整包拣货」必须新增一条**独立的写入路径**，不能复用现有产品/批次扫码路径。

---

## 2. 方案定义

**不做模式切换。** 扫包裹号的含义按「本单是否已有该包裹的预留行」自动判定（见 §3）。

```
扫码 → 分发：
  picking → location → product → lot(未命中不消费) → package
                                                      ↓
    ┌─────────────────────────────────────────────────┴──────────────┐
    │ 本单有该包的预留行（picked=False） → 整包拣货                     │
    │ 本单无该包行 + 有已拣未装包行      → 装包（现有 _bind_to_package）│
    │ 两者都有                          → 整包拣货 + 提示剩余未装包行   │
    │ 都没有                            → 提示「不属于本单 / 包为空」   │
    └────────────────────────────────────────────────────────────────┘
```

---

## 3. 语义判定（G1）— 待确认

扫一个包裹号时，系统的两种意图：

- **装包**：把刚拣好的散货放进这个箱子（`result_package_id = pkg`）
- **整包拣货**：把这个箱子整体搬走（箱内预留行 `picked = True`）

判定规则（**建议值，待确认**）：

| 条件 | 判定 |
|---|---|
| 本单存在 `(package_id = pkg or result_package_id = pkg)` 且 `picked=False` 的行 | 整包拣货 |
| 无上述行，且本单存在 `picked=True and result_package_id=False` 的行 | 装包 |
| 两类行都存在 | **整包拣货优先**，成功后提示「另有 N 件已拣未装包」 |
| 都无 | 提示，不写任何数据 |

> **需拍板**：第三行是「整包优先」还是「拒绝并要求先处理」？建议整包优先（少一次点击，且装包可随时再做）。

---

## 4. 分发顺序与「未命中不消费」

保持 lot 在 package 之前，只把 lot 扫描器改成**未命中时返回 False**：

```python
# _create_new_lot_flow L1416-1422 的改动方向
if not self.picking_id.use_create_lots:
    return False          # 原来是：_set_message("error", ...) + return True
```

配套处理（否则会丢掉有用的错误提示）：

- `_process_barcode` 全部扫描器都返回 False 后，若「有产品/SN 扫描上下文 且 `use_create_lots=False`」，仍显示原来的
  `Serial number/lot %s does not exist. This operation type does not allow creating new ones.`
- 否则显示通用 `Barcode not found: %s`。

> 这样既保证包裹扫描器能拿到条码，又不牺牲「扫错 SN」时的精确报错。

**残留歧义**：某字符串既是「其他产品的已存在批次」又是「包裹名」时，lot fallback 会先命中并消费，包裹永远到不了。概率极低，遇到时在消息里提示「该条码也可作为包裹 X 使用」即可（不做自动猜）。

---

## 5. 数量与超量（G2）— 已定

**整包 = 全有或全无，绝不部分拣。**

| 情形 | 处理 |
|---|---|
| 包内本单数量 ≤ 剩余需求 | 全部置 `picked=True`，`quantity` 保持预留值不变 |
| 包内本单数量 > 剩余需求 且 policy=`allow` | 全部置 `picked=True`（允许超量），提示「超拣 N 件」 |
| 包内本单数量 > 剩余需求 且 policy=`warn` | **整包拒绝**，置 `visible_force_*` 等确认；确认后按 allow 执行 |
| 包内本单数量 > 剩余需求 且 policy=`forbid` | **整包拒绝**，**一行都不改**（校验必须早于任何 write） |

理由：整包出货物理上不可拆；如果只拣一部分，包裹归属与实际货物不符，后续必出对账问题。

---

## 6. 跨单守卫（保留）

整包扫描必须对包内每个 **serial** 复用 `_get_lot_pick_error` 的判断（L1811-1827），但改为**一次批量查询**：

```python
lot_ids = lines.mapped("lot_id").ids
conflicts = env["stock.move.line"].search([
    ("picking_id", "!=", picking.id),
    ("picking_id", "!=", False),
    ("lot_id", "in", lot_ids),
    ("state", "not in", ("done", "cancel")),
])
```

- 有冲突 → **整包拒绝**，消息列出冲突单据名（如 `WH/OUT/00053`）。
- 仅 `lot` tracking 不检查：同一批号可合法分给多张单（quant 拆分）。
- 不做「跳过检查」的开关；确需强行发货，走人工解锁另一张单的预留。

### 6.1 为什么 WH/OUT/00053 会卡住 WH/INT/00001

一个序列号同一时刻只能被**一张单**预留（`stock.quant.reserved_quantity`）。

```
WH/OUT/00053（发货）已 assigned → 该 SN 的 quant 被它预留
        ↓  同时
WH/INT/00001（调拨）也要这同一个 SN
        ↓
系统判定：同一件货被承诺给两张单 → 拒绝（防重复发货）
```

这是**正确的保护**，不是 bug。可行的做法：

1. **顺序正确**（推荐）：先做 INT 调拨 → 到货后再 reserve OUT。此时 OUT 通常还是 `confirmed`、没有 move line，守卫不会触发。
2. **释放再重占用**：把 OUT `action_unassign`（取消预留），做完 INT，再 `action_assign`。
3. 若业务确实要求「OUT 先预留、INT 后挪货」，需要人工确认哪张单优先，系统不应自动放行。

> 待确认：是否要提供 `barcode_cross_order_policy`（forbid/warn）让少数场景可确认后放行？建议首期只做 forbid + 明确提示。

---

## 7. 写入规则（G4）

命中行（`picking = 本单`、`state ∉ (done,cancel)`、`picked=False`、`package_id = pkg or result_package_id = pkg`）：

```python
vals = {
    "picked": True,               # 唯一必须改的字段
    "result_package_id": pkg.id,   # 目标包
    # quantity 保持预留值，不改
}
if not line.package_id:
    vals["package_id"] = pkg.id    # 源包为空才补
elif line.package_id != pkg:
    # 数据不一致：跳过该行并告警，不覆盖
```

- **不**设置 `move.picked`（它由 move line 计算，反向写会误标整个 move）。
- 源库位校验：`line.location_id` 必须与扫描源位一致；不一致则该行跳过并列入提示。
- 一次 `write()` 批量提交，不逐行 `write`。

---

## 8. 包内非本单货 / 空包 / 混合包（G5）— 已定

| 情形 | 处理 | 消息示例 |
|---|---|---|
| 包内部分行属本单，部分属他单 | **只拣本单的**，其余留在包内 | `包裹 PACK0000036：本单 8 件已拣；包内另有 2 件属其他单据，未处理` |
| 包内全部属他单 | 拒绝，不写 | `包裹 PACK0000036 中没有本单的货物` |
| 包内本单行已全部 picked | 幂等返回 | `包裹 PACK0000036 已拣完` |
| 包裹不存在 | 不消费条码，继续后续扫描 | （最终 `Barcode not found`） |
| 包裹为空（无 quant、无行） | 拒绝 | `包裹 PACK0000036 是空的` |
| 行源库位 ≠ 扫描源位 | 跳过并提示 | `包裹 PACK0000036：2 件不在源库位 %s，未处理` |

> 与 v1 的 D8 一致：**不**新建额外行、**不**因为包内混了他单货就整体拒绝。

---

## 9. 撤销（G3）— 新增

现有 `action_unpack_package` 只清 `result_package_id`，**不清 `picked`**，所以整包扫错后无法回到「未拣」。

新增：

```python
def action_undo_package_scan(self, package_id):
    """撤销本单该包裹的整包拣货：picked=False，清 result_package_id。"""
    lines = self.env["stock.move.line"].search([
        ("picking_id", "=", self.picking_id.id),
        ("state", "not in", ("done", "cancel")),
        ("picked", "=", True),
        "|", ("package_id", "=", package_id), ("result_package_id", "=", package_id),
    ])
    if not lines:
        self._set_message("info", self.env._("Nothing to undo in this package."))
        return True
    lines.write({"picked": False, "result_package_id": False})
    self._set_message("info", self.env._("Package %s scan undone.", package_id))
```

**交互（建议）**：同一包裹**连续扫第二次** → 弹确认框（复用现有 `window.confirm` 风格）→ 确认后执行撤销。

为什么不用重扫直接撤销：扫码枪连扫很常见，直接撤销会误伤；必须有确认。

### 9.1 与 unpack 的分工

| 动作 | 语义 | 效果 |
|---|---|---|
| `action_unpack_package` | 装好了，想换个包 | 清 `result_package_id`，`picked` 保持 |
| `action_undo_package_scan` | 扫错了，撤掉 | `picked=False` + 清 `result_package_id` |

---

## 10. 幂等 / 性能 / 验证联动

- **幂等**：重复扫同一包裹且全部已拣 → info，不重复加数量。
- **性能**：整包一次 `write`；跨单守卫一次 `search`；不做逐行 `_get_lot_pick_error`。
- **验证联动**：整包拣货后 `_lines_need_pack` 天然满足；需回归 `barcode_require_pack="mandatory"`（After Each Product）路径，确认不会因「一次扫整包」误报。

---

## 11. 错误提示矩阵

| 场景 | 类型 | 文案（要点） |
|---|---|---|
| 包裹不存在 | 静默 → not_found | `Barcode not found: X` |
| 包裹为空 | error | `包裹 X 是空的` |
| 无本单货物 | error | `包裹 X 中没有本单的货物` |
| 已全部拣完 | info | `包裹 X 已拣完` |
| 超量 forbid | error | `超出剩余需求 N 件，策略禁止超拣` |
| 超量 warn | more_match | `超出剩余需求 N 件，确认后继续` |
| 跨单占用 | error | `SN X 已被其他单据预留（WH/OUT/00053）` |
| 部分行源位不符 | info | `包裹 X：N 件不在源库位，未处理` |
| 部分行属他单 | info | `包裹 X：本单 N 件已拣；另有 M 件属其他单据` |
| 已装包数据不一致 | warn | `行 Y 的源包与扫描包裹不一致，已跳过` |

---

## 12. 待确认决策

| # | 决策 | 建议值 | 状态 |
|---|---|---|---|
| D-A | 两类行并存时判定（§3） | 整包优先 | **待确认** |
| D-B | 超量 warn 是否整包确认 | 是（整包拒绝→确认→整包执行） | 已定 |
| D-C | 包内他单货物 | 只拣本单 + 提示 | 已定 |
| D-D | 撤销交互 | 重扫同包 + 确认框 | 已定 |
| D-E | 跨单守卫是否可放行 | 不放行，仅改提示 | 已定 |
| D-F | 是否统计「包内共 M 件」 | 是，消息里体现 | 已定 |

---

## 13. 实施顺序

1. **阶段一（后端）**：`_scan_package` 语义判定 + `_process_package_scan` 写入 + 超量/跨单校验 + 未命中不消费。
2. **阶段二（撤销）**：`action_undo_package_scan` + 前端重扫确认。
3. **阶段三（UI）**：`get_scan_state` 增加 `has_package_moves`、`package_scan_hint`；前端提示条。
4. **阶段四**：回归 + 文档更新（RULES.md 补 1.1.6 例外）。

---

## 14. 测试清单

| # | 用例 | 断言 |
|---|---|---|
| 1 | 整包正常拣货 | 全部行 `picked=True`，`result_package_id` 保留 |
| 2 | 包内部分行已拣 | 只改未拣行，消息含「已拣 N 件」 |
| 3 | 重复扫同包 | 幂等，数量不变 |
| 4 | 超量 allow | 全部 `picked=True`，超拣提示 |
| 5 | 超量 warn | 先拒绝，确认后执行 |
| 6 | 超量 forbid | **一行都没改**（关键：校验早于 write） |
| 7 | 跨单占用 | 拒绝，消息含单据名 |
| 8 | 包内非本单货 | 只拣本单，其余 `picked=False` |
| 9 | 空包 | 拒绝，不改数据 |
| 10 | 混合包（装包 vs 整包） | 按 §3 判定规则走对应分支 |
| 11 | 撤销 | `picked=False`、`result_package_id` 清空 |
| 12 | 验证 + backorder | 整包拣货后可正常验证 |
| 13 | 无 `stock.group_tracking_lot` | 包裹功能不显示/不触发 |

---

## 15. 明确不做

- 不做模式开关、不做「切换模式时清空包裹」的破坏性操作；
- 不改原生 `button_validate` / backorder；
- 不改 `barcode_require_pack` 语义；
- 前端不做业务判断（全部后端返回结果）；
- 首期不做「包内逐件改数量」。
