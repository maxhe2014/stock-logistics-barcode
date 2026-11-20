# Stock Barcodes Picking 规则修正 TO-DO LIST

> 模块：`stock_barcodes_picking`  
> 规则基线：`19.0.1.1.1`  
> 整理日期：2026-11-04  
> 当前状态：**问题说明与实施待办，尚未修改业务代码**  
> 完整规则依据：[RULES.md](RULES.md)
>
> 2026-11-19 追加：第 8 节「扫码工作台入口页」是独立的新页面计划，与前述规则修正分开跟踪，确认口径后再编码。

## 1. 这份文档要解决什么

这 5 项问题并不只是“提示语不清楚”，而是涉及三个更底层的问题：

1. **系统有没有正确理解当前业务。**例如客户退货虽然也是收货，但货应当从客户位置回来，不能按普通内部调拨判断。
2. **界面选中的对象和后台实际修改的对象是否一致。**例如界面选中了 B 行，后台却把数量写到了 A 行。
3. **同一个规则是否在每一个入口都生效。**例如普通扫码有候选单保护，删除操作却没有同样的保护。

后续修正时，不能只让某个测试场景“通过”，还要把作用范围说清楚：到底针对整张调拨单、某一条需求行，还是某一条实际明细。

## 2. 先统一几个名词

| 名词 | 通俗解释 |
|---|---|
| Picking / 调拨单 | 一整张出入库或内部调拨任务。 |
| Move / 需求行 | 单据上“要移动什么产品、需要多少”的一行。同一产品可能在单据上出现多行。 |
| Move Line / 实际明细 | 实际拣货时“从哪个库位、用哪个批次、拣了多少、放进哪个包装”的记录。一条需求行可以对应多条实际明细。 |
| `active_move_id` | 扫码页当前高亮、被操作员选中的需求行。 |
| Lot / 批次 | 一批产品共用的批次号。 |
| SN / 序列号 | 单件产品独有的编号。 |
| Package / 包装 | 已拣商品放入的箱子、托盘等包装。 |
| 候选单状态 | 扫到一个单号后，系统找到多张可能的调拨单，正在等待操作员选择。此时不应继续修改旧单。 |

## 3. 总任务表

| 编号 | 待办事项 | 风险 | 是否需要先确认业务口径 | 当前状态 |
|---|---|---|---|---|
| TODO-01 | 修正源库位只允许 `internal` 与收货、退货的冲突 | 高 | 是：确认各业务允许的源位类型 | 待处理 |
| TODO-02 | 让当前选中需求行与实际写入需求行保持一致 | 高 | 是：选择“按行”还是“按产品聚合” | 待处理 |
| TODO-03 | 给同批次多明细、跨包装操作补上准确明细身份 | 高 | 已确认：普通扫码默认未包装，包装明细仅允许显式行操作 | 已完成包装维度；active move 颗粒度归 TODO-02 |
| TODO-04 | 给删除批次/SN 补候选单守卫和服务端范围限制 | 高 | 否，保护规则可以直接补齐 | 部分完成：删除接口守卫与范围限制已补齐 |
| TODO-05 | 统一包装 `mandatory` 的配置名称与实际生效时点 | 中 | 是：确认“逐产品装箱”还是“验证前装箱” | 待处理 |

### 建议实施顺序

1. **先做 TODO-04**：范围小、规则明确，先堵住候选单状态下误改旧单的入口。
2. **再做 TODO-01**：恢复供应商收货和客户退货的正常扫码流程。
3. **然后确定并实施 TODO-02**：先统一“当前行”的写入口径。
4. **基于 TODO-02 做 TODO-03**：写入目标明确后，再把定位精度补到具体明细和包装。
5. **最后处理 TODO-05**：根据实际包装作业方式选择规则，避免边拣边装与最终检查相互冲突。

---

## TODO-01：源库位只允许 `internal`，与收货、退货冲突

### 1. 问题一句话

系统把“合法源库位”简单理解成“必须是仓库内部库位”，但供应商收货和客户退货的起点本来就不是内部库位，所以合法业务会在扫描源库位时被拒绝。

### 2. 现在系统怎么做

扫描源库位时，代码只接受：

```text
location.usage == "internal"
```

只要扫描的是 `Customers`、`Vendors` 等非内部位置，就直接提示“只能扫描内部库位”，不会继续执行后面的序列号库存检查。

源码：[Wizard `_scan_location()`](wizard/stock_barcodes_picking.py#L765-L794)

### 3. 通俗理解

可以把它理解成仓库门口只有一个判断：

> “你不是仓库里面的位置，所以一律不能作为发货起点。”

这个判断对普通出库通常合理，但对以下业务过于简单：

- **供应商收货**：货从供应商位置进入仓库，源位通常是 `Vendors`。
- **客户退货**：货从客户位置退回仓库，源位通常是 `Customers`。
- **内部调拨**：货从仓库内部一个位置移动到另一个位置，源位通常是 `internal`。

这三类业务的“合理源位”并不相同，不能共用一条“只准 internal”的规则。

### 4. 实际例子：客户退货

以之前处理的退货场景为例：

1. 退货单要求序列号 `00000878762301107637` 从 `Customers` 退回 `WH/Stock`。
2. 如果该序列号实际还在 `WH/Stock`，系统应当在扫 SN 时提示“客户源位没有这个货”。
3. 但在开启“扫描源库位”的情况下，操作员先扫 `Customers`，就会更早被“只能扫描内部库位”拒绝。
4. 结果是：后面已经修好的退货源库存检查根本没有机会执行。

也就是说，当前不是“库存检查错了”，而是**更前面的库位入口规则把合法业务挡住了**。

### 5. 可能带来的影响

- 操作员无法正常开始供应商收货或客户退货。
- 为了绕过限制，操作员可能改选一个内部库位，但这会把业务方向改错，不应作为正常解决方案。
- 关闭源库位扫描时，系统会直接使用单据默认源位，问题可能暂时不出现，导致同一个业务在不同配置下表现不同。
- 现有退货测试主要验证 SN 库存检查，尚不足以证明“开启源位扫描后，完整流程也能走通”。

### 6. 建议的目标规则

不要再使用全局单一的 `internal` 限制，应按当前调拨业务判断源位是否合理。

建议先确认下面这张业务矩阵：

| 业务类型 | 通常合理的源位 | 建议处理 |
|---|---|---|
| 普通销售出库 | `internal` | 继续要求内部源位。 |
| 仓库内部调拨 | `internal` | 继续要求内部源位。 |
| 普通供应商收货 | `supplier` | 允许供应商源位。 |
| 客户退货 | `customer` | 允许客户源位。 |
| 运输途中、直运等特殊流程 | 可能涉及 `transit` 等 | 必须明确列入支持范围，不能默认放行或默认拒绝。 |

同时建议保留一条底线：

> 当前 picking 默认源位本身应当是合法参考。扫描库位是否允许，需要与单据方向、默认源位和退货身份一起判断，而不是只看 usage。

### 7. 修改任务

- [ ] 确认各作业类型允许扫描的源位 usage，以及是否支持 `transit` 等特殊位置。
- [ ] 将 `_scan_location()` 从“全局只认 internal”改为“按当前 picking 业务判断”。
- [ ] 明确客户退货的识别方式继续使用 `incoming + return_id`，不要误伤普通供应商收货。
- [ ] 保留现有 SN 源库存校验：合法源位被接受后，仍必须检查该 SN 是否真的位于源位。
- [ ] 检查源库位子层级的规则，避免只修 usage 后又出现父子库位不一致。
- [ ] 同步更新 RULES.md 中 LOC-002、ISS-001 和相关测试矩阵。

### 8. 验收标准

- [ ] 开启源库位扫描后，普通供应商收货可以扫描合法 `Vendors` 源位并继续。
- [ ] 开启源库位扫描后，客户退货可以扫描合法 `Customers` 源位并继续。
- [ ] 合法客户退货源位被接受后，源位无货的 SN 仍会在扫码阶段被拒绝。
- [ ] 普通销售出库仍不能随意使用 `Customers`、`Vendors` 作为源位。
- [ ] 内部调拨的原有库位规则不回退。
- [ ] 开启和关闭源库位扫描两种配置下，业务结论一致，只是操作步骤不同。
- [ ] 原供应商收货、合法客户退货、错误客户退货测试继续通过，并新增“先扫描源位”的完整测试。

---

## TODO-02：当前选中的 `active_move_id` 不一定是实际写入行

### 1. 问题一句话

界面上操作员选中的是某一条需求行，但后台写入时却按“同产品的所有需求行”一起查找和计算，所以选中的行和真正被修改的行可能不是同一行。

### 2. 现在系统怎么做

点击产品行时，系统会保存 `active_move_id`，界面也会高亮这一行，看起来像“后续扫码就处理这一行”。

但真正写入明细时，后台会：

1. 找出当前 picking 中所有同产品、非取消的 move。
2. 在这些 move 的明细中按产品、源库位、批次查找。
3. 不使用 `active_move_id` 限定匹配范围。
4. 需要新建明细时，写入同产品的第一条 move，即 `moves[:1]`。
5. 计算需求和超量时，也汇总同产品所有 move 的需求。

源码：

- [Wizard `set_active_move()`](wizard/stock_barcodes_picking.py#L2051-L2067)
- [Wizard `_process_stock_move_line()`](wizard/stock_barcodes_picking.py#L1565-L1733)

### 3. 通俗理解

界面向操作员表达的是：

> “你选中了哪一行，我就处理哪一行。”

后台实际表达的却是：

> “只要产品相同，我就把这些行放在一起处理。”

当一张单据中同一产品只有一行时，两种做法看不出差别；一旦同产品有多行，差别就会暴露。

### 4. 实际例子

假设同一张调拨单有两行：

| 需求行 | 产品 | 需求数量 | 说明 |
|---|---|---:|---|
| A | 山地车 2 | 5 | 第一行 |
| B | 山地车 2 | 5 | 第二行 |

操作员点击 B，B 被高亮，然后扫描产品并确认数量 5。

当前后台可能出现：

- 新建实际明细时落到 A，因为 A 是同产品第一条 move。
- 如果 A 已有相同产品、源位、批次的明细，也可能直接更新 A 的明细。
- 即使操作员想处理的是 B，超量判断仍可能按 A＋B 的总需求 10 计算。
- 在 B 上操作 6 件，未必立即提示超过 B 的需求 5，因为系统看到的是合计需求 10。

这会让“选中行”变成一个主要影响界面高亮和搜索提示的状态，而不是可靠的写入目标。

### 5. 可能带来的影响

- 需求行 A、B 的完成数量与操作员理解不一致。
- 按需求行区分库位、批次、订单来源或其他业务含义时，数据可能写到错误行。
- 超量提示可能提前或延后，不能准确反映当前行容量。
- 后续按行对账、按行删除、按包装核对时，很难解释数量为什么发生变化。
- 现有单 move 测试无法发现这个问题。

### 6. 建议的目标规则

建议优先采用**按需求行写入**，因为它与当前界面表达最一致：

1. 有 `active_move_id` 且产品一致时，只在这一个 move 内匹配、计算和创建明细。
2. 没有选中行时，扫产品可以自动选中该产品的一条明确目标行，并让界面先显示这个目标。
3. 超量需求、已拣数量、容量重分配都按同一个目标 move 计算。
4. 操作员要处理另一行时，先点击另一行，再继续扫码。

如果业务坚持“同产品聚合”，则应反向调整界面：

- 不再把单个 move 高亮表达成唯一写入目标。
- 按产品合并显示需求与已拣数量。
- 明确后台会自动在同产品各行之间分配数量。

两种方案都可以讨论，但不能继续保持“界面按行、后台按产品”的混合状态。

### 7. 修改任务

- [ ] 确认目标方案：按需求行写入，还是按产品聚合并合并 UI。
- [ ] 若采用按行写入，将 `_process_stock_move_line()` 的目标 move 集合限定为当前有效 active move。
- [ ] 明确无 active move 时的自动选择规则，确保自动选择结果在界面上可见。
- [ ] 统一匹配明细、需求汇总、超量判断、容量重分配和新建明细的 move 范围。
- [ ] 检查 Consume by demand、Consume with qty、单据外产品新增和唯一 SN 自动切产品是否遵循同一口径。
- [ ] 保留同产品连续扫码的 active move 保持行为，不要每次扫码都跳回第一条。
- [ ] 同步更新 RULES.md 中 CTX-006、QTY-002、QTY-006、QTY-012、ISS-003。

### 8. 验收标准

- [ ] 同产品有 A、B 两行时，选中 B 后扫码只改变 B，A 的需求行和明细保持不变。
- [ ] 选中 B 后，超量按 B 的需求判断，不使用 A 的剩余需求抵消。
- [ ] 新建明细落在当前选中的 move，不再固定落到同产品第一条 move。
- [ ] 切换 active move 后，后续普通产品、批次和 SN 扫码都跟随新目标。
- [ ] 无 active move 的自动选择行为明确，并与界面高亮一致。
- [ ] 同产品单 move 的原有 SET、超量 allow/warn/forbid、容量重分配测试不回退。
- [ ] 新增同产品多 move 的普通产品、批次和序列号测试。

---

## TODO-03：同 lot 多明细、跨包装时缺少准确明细维度

### 1. 问题一句话

系统目前主要靠“需求行＋批次”找到要更新或删除的记录，但同一个批次可能拆成多行、放进多个包装；只凭这两个条件无法知道操作员到底指向哪一条。

### 2. 现在系统怎么做

#### 写入时

明细匹配主要使用：

```text
产品 + 源库位 + 批次
```

匹配范围还可能覆盖同产品的多个 move。匹配结果有多条时，只取第一条 `existing_lines[:1]` 设置数量。

匹配条件中没有：

- 当前 `active_move_id`。
- `result_package_id` 包装。
- 具体的 `stock.move.line.id`。

#### 删除时

前端删除按钮向后端传入：

```text
move_id + lot_id
```

后端搜索符合条件的活动明细后，只处理第一条：

- 数量大于 1：减 1。
- 否则：删除整条。

前端虽然按包装分行显示，但删除请求没有把当前包装或具体明细 ID 传给后端。

源码：

- [Wizard 明细匹配与首行写入](wizard/stock_barcodes_picking.py#L1591-L1600)
- [Wizard `action_remove_move_lot()`](wizard/stock_barcodes_picking.py#L2187-L2234)
- [OWL 删除请求](static/src/picking_scan_app.esm.js#L552-L572)
- [OWL 包装行分组](static/src/picking_scan_app.esm.js#L1011-L1028)

### 3. 通俗理解

这相当于操作员指着“B 箱里的那件商品”说删除，但交给后台的信息只有：

> “这个产品、这个批次，帮我找一条处理。”

后台不知道操作员指的是 A 箱还是 B 箱，只能按查询顺序取第一条。只要数据顺序与界面看到的不一致，就可能处理错对象。

### 4. 实际例子

同一需求行、同一批次 `L001` 共 10 件，被拆成：

| 实际明细 | 包装 | 数量 |
|---|---|---:|
| 明细 1 | Package A | 6 |
| 明细 2 | Package B | 4 |

操作员在 Package B 那一行点击删除。

当前后台只收到“该 move＋L001”，没有收到 Package B 或明细 2 的 ID，因此可能：

- 删除明细 1，而不是明细 2。
- 把明细 1 的数量从 6 减为 5，Package B 仍然是 4。
- 后续扫码更新时也命中 Package A 的明细，而不是当前未包装或目标包装明细。

界面看起来是在操作 B，数据库却改变了 A，这就是典型的颗粒度不一致。

### 5. 可能带来的影响

- 删除错包装中的商品，包装内容与实物不一致。
- 后续扫码改写已经装箱的明细，导致包装数量被悄悄改变。
- 同批次多行时，数量变化难以追溯。
- 验证、打印装箱单或按包装发货时才发现差异，纠正成本更高。

### 6. 建议的目标规则

最稳妥的方式是：**需要操作某一条已存在明细时，直接传递具体的 `stock.move.line.id`。**

建议规则如下：

1. 后端状态快照为每个可操作明细提供真实 move line ID。
2. 删除按钮传 move line ID，不再只传 move＋lot。
3. 服务端重新检查该明细确实属于当前 picking，并满足当前操作条件。
4. 已包装明细默认视为“已封存”，后续普通扫码优先更新当前未包装明细，不自动修改包装内数量。
5. 如果确实需要修改包装内明细，必须来自该包装下明确的行操作，而不是模糊匹配。
6. 包装仍然可以按整单装箱，但“装箱范围”和“单条明细修改”要分开处理。

### 7. 与 TODO-02 的关系

- TODO-02 先解决“写哪一条 move”。
- TODO-03 再解决“写这一条 move 下的哪一条 move line”。

两者不能互相替代。即使已经限定 active move，同一 move 下同 lot 的多个包装明细仍然需要准确区分。

### 8. 修改任务

- [x] 已确认已包装明细默认禁止被后续普通扫码改写；包装内数量只能通过显式明细操作调整。
- [x] 在后端扫描状态中提供可唯一定位的 move line ID。
- [x] 将删除接口改为按具体 move line 操作，并保留服务端 picking 归属校验。
- [x] 普通扫码匹配、累加基数及重分配均区分未包装与已包装。
- [ ] 同一未包装分组仍可能有多条明细，active move 与更细写入颗粒度继续由 TODO-02 跟踪。
- [x] 普通批号数量大于 1 时减 1，数量为 1 时删行；多明细先展开再逐行操作。
- [x] 修改与删除共用真实明细服务端校验，不只是修改前端参数。
- [ ] 历史基线条目 QTY-003、ACT-001、PACK-012、ISS-006 的回写另行整理；当前规则见 RULES 第 23、24 节。

### 9. 验收标准

- [x] 同 move、同 lot 分布在 Package A/B 时，删除 B 只影响 B 对应明细。
- [x] 删除数量大于 1 的明细时，只减少目标明细，其他明细数量完全不变。
- [x] 后续普通扫码不会悄悄修改已包装明细，只有显式行操作可以调整包装内容。
- [x] 同 lot 未包装与已包装同时存在时，普通扫码只累加未包装明细。
- [x] 传入其他 picking 的 move line ID 时，服务端拒绝且不产生任何写入。
- [x] 同 lot 单行、无包装的旧流程不回退。

### 10. 本轮完成范围（`19.0.1.1.5`）

- [x] 状态快照为每个已拣批号返回真实明细 ID、数量、源库位和包装元数据；展示合计与操作身份分离。
- [x] 新增按 `stock.move.line.id` SET 数量的显式修改接口；同批号、同产品的其他明细不变。
- [x] 删除接口改为按真实明细 ID 操作，保留普通批号数量大于 1 时减 1、数量为 1 时删行的规则。
- [x] 同批号多明细时先展开源库位/包装明细，由操作员逐行选择；单明细直接进入数量编辑。
- [x] 外部 picking 明细、未拣预留明细均由服务端拒绝；跨包装修改/删除只影响目标行。
- [ ] 普通扫码命中已包装明细、当前操作包装匹配及 active move 写入颗粒度不在本轮范围内，仍按上方后续任务处理。

### 11. 本轮完成范围（`19.0.1.1.6`）

- [x] 普通批号再次扫码时，累加基数只取同产品、同库位、同批号的未包装已拣数量。
- [x] 普通扫码和 SN 占位行匹配均排除已包装明细；只有包装行时新建未包装行，新行显式不写 `result_package_id`。
- [x] 新批号需要容量重分配时只从未包装行扣减；已包装数量仍参与总需求/超量计算。
- [x] `allow`、`warn` 二次确认和 `forbid` 禁止强制绕过均保持原策略，包装数量在全过程不变。
- [x] 同批号分布在多个包装、包装与未包装并存、新 SN 及状态快照分组均有回归覆盖；全量 77 个测试通过。
- [ ] active move 多需求行写入颗粒度不属于包装规则，本项继续由 TODO-02 跟踪。

### 12. 本轮完成范围（`19.0.1.1.7`）

- [x] 高亮目标从“新出现的批号 ID”改为“同一包装分组内数量增加的批号”，支持已存在批号重复扫码。
- [x] 高亮身份包含 `row_key`，同一批号跨包装时只定位实际增加的未包装分组。
- [x] 通过高亮 nonce 更新批号节点 key，连续扫同一批号也会重新开始闪烁动画。
- [x] 新增同批号包装 1 件、未包装 10 件再扫码的状态快照回归；全量 78 个测试通过。

---

## TODO-04：删除批次/SN 缺少候选单服务端守卫

### 1. 问题一句话

系统正在等待操作员选择候选调拨单时，大多数写操作都会被阻止，但删除批次/SN 没有走同一道保护，仍可能修改旧调拨单。

### 2. 现在系统怎么做

当扫描结果对应多张 picking 时，系统会：

1. 保留旧 picking 作为背景。
2. 打开候选单选择器。
3. 要求操作员先选择其中一张。

常规写操作会调用 `_check_selector_resolved()`：只要候选选择器还开着，就提示“先选择调拨单”并停止。

但是 `action_remove_move_lot()` 没有调用这个共享守卫。它只检查 move 是否属于当前旧 picking，然后继续删除或减少明细数量。

此外：

- UI 只给 `picked=True` 的批次/SN 显示删除按钮。
- 后端删除方法本身没有限制 `picked=True`。

源码：

- [Wizard 共享候选单守卫](wizard/stock_barcodes_picking.py#L682-L701)
- [Wizard `action_remove_move_lot()`](wizard/stock_barcodes_picking.py#L2187-L2234)
- [XML 删除按钮](static/src/picking_scan_app.xml#L253-L340)

### 3. 通俗理解

候选单状态就像系统正在问：

> “你刚才说的是哪一张单？先选清楚。”

其他按钮都会等回答后再执行，删除按钮却没有检查这个问题，仍可能拿着旧单继续操作。

即使前端以后把按钮隐藏，也不能代替服务端检查，因为 RPC 可以直接调用后端方法。

### 4. 实际例子

1. 操作员正在处理调拨单 A。
2. 扫到一个单号后，系统找到多张候选单，于是弹出候选列表。
3. 此时正确行为是：所有会修改库存明细的动作都暂停。
4. 但删除动作没有候选单守卫，仍可能按旧 picking A 找到明细并删除或减少数量。
5. 操作员以为自己还在处理“选择新单”，实际旧单 A 已经被改动。

另外，如果绕过界面直接传入未 picked 的预留明细条件，后端也没有明确拒绝，这比界面允许的操作范围更宽。

### 5. 可能带来的影响

- 候选单尚未确认时误改旧单。
- 前端与后端规则不一致，单纯隐藏按钮无法保证安全。
- 可能删除或减少未拣预留明细，破坏原预留状态。
- 出现“没有看到明确扫码成功，却发现原单明细变了”的难排查问题。

### 6. 建议的目标规则

1. 所有会新增、修改、删除 picking 业务数据的 action，都必须先通过候选单守卫。
2. 删除操作必须验证目标属于当前 picking。
3. 删除批次/SN 只允许处理已 picked 明细，与 UI 表达保持一致；如确需删除预留，应设计独立入口和提示。
4. 守卫失败时不得部分写入，也不得清理目标 picking 的数据。
5. 与 TODO-03 合并后，最终应校验具体 move line ID，而不是继续扩大到模糊搜索。

### 7. 修改任务

- [ ] 在 `action_remove_move_lot()` 入口调用 `_check_selector_resolved()`。
- [ ] 增加目标明细 `picked=True` 的服务端限制。
- [ ] 保留并强化当前 picking 归属校验。
- [ ] 检查所有其他会写业务数据的 action，确认共享守卫没有类似遗漏。
- [ ] 候选单未解决时，扫码、确认、消耗、包装、删除、强制添加和验证应有一致结果。
- [ ] 增加失败前后明细快照对比，证明守卫失败时没有任何业务写入。
- [ ] 同步更新 RULES.md 中 DSP-004、ACT-001、ACT-002、ISS-008。

### 8. 验收标准

- [x] 候选单选择器打开时调用删除，返回“请先选择调拨单”类错误。
- [x] 删除被拒绝后，目标明细数量、ID、picked 状态保持不变。
- [x] 直接 RPC 也不能绕过候选单守卫。
- [x] 未 picked 的预留明细不能通过当前“删除已拣批次/SN”接口被删除或减少。
- [x] 正常无候选单状态下，删除已拣明细仍按确认后的规则工作。
- [ ] 其他写操作的候选单保护不回退。

### 9. 本轮完成范围（`19.0.1.1.5`）

- [x] 修改和删除统一经过 `_check_selector_resolved()`，候选单未解决时拒绝写入。
- [x] 服务端按“明细 ID＋当前 picking”定位，并检查单据/明细状态及 `picked=True`，直接 RPC 也不能绕过。
- [x] 守卫失败、外部明细和未拣预留明细的回归断言均检查目标 ID、数量及 picked 状态未被修改。
- [x] 正常状态下的精确减 1、删行和 SN 删除保留原有业务语义。
- [ ] 全模块其他写操作的专项守卫审计不在本轮增量内，仍按上方任务另行核对。

---

## TODO-05：包装 `mandatory` 实际只在验证时检查

### 1. 问题一句话

配置名称表达的是“每个产品之后必须包装”，但代码实际是在“整张调拨单验证之前”才检查；配置说法与执行时点不一致。

### 2. 现在系统怎么做

作业类型中：

```text
barcode_require_pack = mandatory
```

对应文案是 `Mandatory After Each Product`，容易让管理员理解为：

> 每确认一个产品，就必须先把它放进包装，才能继续下一个产品。

但当前代码在逐产品 `action_confirm()` 中没有包装检查。实际操作可以是：

1. 扫产品 A 并确认，不包装，成功。
2. 扫产品 B 并确认，不包装，也成功。
3. 继续处理其他产品，不受 mandatory 影响。
4. 最后点击 Validate，才发现存在已拣未包装明细，整单被阻止验证。

源码：

- [Picking Type 包装配置](models/stock_picking_type.py#L32-L43)
- [Wizard 验证前包装检查](wizard/stock_barcodes_picking.py#L1840-L1858)

### 3. 通俗理解

配置听起来像：

> “每装好一种货，就要马上装箱。”

系统实际做的是：

> “拣货过程中可以先不装箱，最后整单出库前再统一检查。”

这两种管理方式的差异很大：

- 前者约束日常拣货动作，问题会在操作过程中暴露。
- 后者允许最后统一装箱，但可能到验证时才集中返工。

### 4. 实际例子

一张 picking 有产品 A、B、C，作业类型设为 mandatory。

当前结果：

| 操作 | 当前是否允许 |
|---|---|
| A 已拣但不包装，继续扫 B | 允许 |
| B 已拣但不包装，继续扫 C | 允许 |
| 所有产品都未包装，点击 Validate | 拒绝 |
| A 未 picked 的预留明细没有包装 | 不参与当前检查 |
| 已 picked 明细中至少一条未包装 | Validate 被拒绝 |

所以当前准确名称应当是“验证前必须将所有已拣明细包装”，而不是“每个产品后必须包装”。

### 5. 可能带来的影响

- 管理员按字面配置，却得到另一种作业流程。
- 操作员直到最后验证才发现包装遗漏，需要回头逐单排查。
- 后续开发者可能按字段名称在 Confirm 中再增加一道检查，造成重复或更严格的意外变化。
- 序列号逐件确认时，“每个产品后”到底指每扫一件还是一种产品全部完成，也会产生新的歧义。

### 6. 需要先确认的业务口径

#### 方案 A：只要求验证前全部包装

如果实际业务允许“先拣完、最后统一装箱”，建议保留当前执行时点：

- 将配置标签改为 `Mandatory Before Validation`。
- 将帮助文本改为“验证前，所有已拣明细必须有包装”。
- 不在每次产品 Confirm 中增加包装拦截。
- 保留 optional＋验证前全部包装、no 三种现有分支。

**如果没有明确的逐产品装箱要求，建议优先选这个方案。**它改动最小，也符合当前代码实际行为。

#### 方案 B：确实要求逐产品完成后包装

如果现场必须边拣边装，则需要先进一步定义：

- “每个产品”是每次 Confirm 后，还是一种产品全部拣完后？
- 序列号逐件扫描时，是否每扫一件就必须装箱？
- 同产品多 move 时，按单行完成还是同产品全部完成？
- 未包装时，是阻止下一产品，还是仅警告？
- 当前整单 Pack 操作会把所有已拣未包装行一起装箱，是否符合逐产品隔离要求？

这些口径未确定前，不建议直接在 `action_confirm()` 里加一个简单判断，否则可能把每次 SN 扫码都卡住。

### 7. 修改任务

- [ ] 确认选择方案 A 还是方案 B。
- [ ] 若选 A：只调整字段标签、帮助文本、翻译和规则文档，保持 Confirm 行为不变。
- [ ] 若选 B：先写出逐产品完成判定、包装范围和下一产品拦截规则，再实施。
- [ ] 明确 mandatory、optional＋验证前全部包装、no 三组配置的差异。
- [ ] 明确检查对象是当前已 picked 明细，未 picked 预留明细不应被误算为待包装实物。
- [ ] 检查整单 Pack 与逐产品包装要求是否冲突。
- [ ] 同步更新 RULES.md 中 CFG-004、PACK-011、ISS-023。

### 8. 验收标准

#### 若选择方案 A

- [ ] 配置页面不再显示容易误解的 After Each Product。
- [ ] 产品确认时仍不要求立即包装。
- [ ] Validate 时准确阻止所有已拣未包装的情况。
- [ ] 全部已拣明细有包装后，可以进入原生验证流程。
- [ ] 未 picked 的预留明细不会单独触发包装拦截。

#### 若选择方案 B

- [ ] 按已确认的“产品完成”颗粒度触发包装检查。
- [ ] 序列号、普通批次、非跟踪产品分别有明确测试。
- [ ] 同产品多 move 的完成判定与 TODO-02 的口径一致。
- [ ] 包装范围不会把其他产品意外混入，或明确说明整单混装是允许的。
- [ ] Validate 前的最终检查仍保留，作为最后兜底。

---

## 4. 跨问题统一目标

实施这 5 项时，建议最终形成下面这套一致规则：

| 操作 | 应使用的明确范围 |
|---|---|
| 扫描源库位 | 按当前 picking 的业务方向判断合法 usage。 |
| 扫产品/批次并写入 | 明确目标 move；界面选中行与后台写入行一致。 |
| 修改或删除已存在明细 | 明确具体 move line，不依赖“查询结果第一条”。 |
| 装箱 | 可以按整单处理，但必须与逐产品包装配置区分。 |
| 候选单未解决时的任何写操作 | 服务端统一拒绝，不能只靠前端隐藏按钮。 |
| 验证前包装检查 | 检查整单已 picked 明细，作为最终兜底。 |

## 5. 实施前需要确认的 4 个决定

- [ ] **决定 1：源位矩阵。**普通收货、客户退货、出库、内部调拨分别允许哪些源位；是否支持 transit 等特殊流程。
- [ ] **决定 2：写入颗粒度。**是否采用本文建议的“active move 就是唯一写入 move”；若否，UI 如何改成产品级表达。
- [ ] **决定 3：已包装明细。**普通后续扫码是否默认不得修改已包装明细；删除是否统一按 move line ID。
- [ ] **决定 4：包装 mandatory。**选择“验证前全部包装”还是“逐产品完成后包装”。

TODO-04 的候选单守卫不依赖上述业务选择，可以优先实施。

## 6. 总体验收与回归清单

### 6.1 核心回归

- [ ] 普通供应商收货：已有 SN 不需要 vendor 位有库存，但源位扫描规则合法。
- [ ] 合法客户退货：SN 在 Customers 源位时可以退回。
- [ ] 错误客户退货：SN 实际仍在 WH/Stock 等其他位置时，扫码即拒绝且不添加明细。
- [ ] 普通出库和内部调拨：已有库位、SN、超量规则不回退。
- [ ] 普通产品 SET、批次创建、序列号自动确认保持原行为。
- [ ] 超量 allow/warn/forbid 和 Force Consume 按新行级口径正确运行。
- [ ] 同产品多 move、同 lot 多行、同 lot 多包装均有直接测试。
- [ ] 候选单状态下所有写操作均不能修改旧 picking。
- [ ] 包装 mandatory/optional/no 及验证前全部包装分支均有直接测试。
- [ ] 原生验证返回 True、包装类型向导、backorder 向导的流程不回退。

### 6.2 每项修复都必须证明

- [ ] 界面显示目标与后台实际写入目标一致。
- [ ] 服务端自己完成权限、归属和状态校验，不依赖前端按钮是否隐藏。
- [ ] 拒绝操作时没有部分业务写入。
- [ ] 成功时只修改预期 picking、move、move line 或 package。
- [ ] 测试同时检查“应改变的记录”和“不应改变的相邻记录”。
- [ ] RULES.md、TO-DO LIST、字段文案和翻译同步更新。

## 7. 完成定义

只有同时满足以下条件，对应 TODO 才能标记完成：

1. 业务口径已经确认，不再依赖“第一条”“同产品都行”这类模糊规则。
2. 后端和前端采用同一颗粒度。
3. 正常场景、拒绝场景和相邻数据不受影响都有测试。
4. 现有 59 个测试方法相关回归通过，并补充本文件要求的边界测试。
5. 规则总表和本待办状态已同步。

---

# 8. 扫码工作台入口页（新，待确认后编码）

> 追加日期：2026-11-19  
> 设计来源：Pixso「手机扫码APP」/ 页面「野兽主题」`7:1188` / frame `52:5192`「扫码工作台」357×1009  
> 目标入口：`/odoo/inventory/1/action-265/action-690`  
> 当前状态：**需求澄清，尚未修改代码**

## 8.1 现状核实

| 项 | 实测结果 |
|---|---|
| `action-265` | `stock.action_picking_tree_ready`（To Do），模型 `stock.picking`，`list,kanban,form,calendar`，context 含 `search_default_available=1`，即“已就绪”的调拨单列表 |
| `action-690` | `stock_barcodes_picking.action_picking_barcode_scan`，客户端动作 `stock_barcodes_picking.PickingScanApp`，现有扫码页 |
| 菜单/入口 | 没有菜单指向 265/690。实际入口是 `stock.picking` 的 list/kanban 视图头部条码按钮（[stock_picking_views.xml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/views/stock_picking_views.xml#L25-L79)）：列表/看板头部按钮在 0 选中时进入“扫码优先”模式，行内按钮进入单张单据；新工作台应替换头部按钮的目标（已确认） |
| 当前扫码页入口 | `PickingScanApp` 依赖 `params.wiz_id`；没有 `wiz_id` 时没有有效单据可扫 → 计划改为重定向到工作台 |
| 当前仓库 | 只有 `WH`（My Company）一个仓库 |
| 当前作业类型 | `WHIN`（Receipts/incoming）、`WHOUT`（Delivery Orders/outgoing）、`WHINT`（Internal Transfers/internal）、`WHPC`（Pick Components/internal）、`WHSFP`（Store Finished Product/internal）；**没有 IA（库存调整）类型的 picking type** |
| 设计中的六类 | OUT、PC、IN、SFP、INT、IA；IA 已确认走 `stock.quant` 盘点（参考 qz_scanner），不新增 picking type（见 §8.6.3） |

**结论**：现状是「To Do 列表/看板头部扫码按钮 → 扫码页」，目标是替换为「扫码工作台 → 状态/类型列表页 → 扫码页」，最近作业可直接进扫码页。工作台与列表页是新页面，现有扫码页保留；行内扫码按钮继续进入单张单据。

## 8.2 目标流程

```text
扫码工作台（新入口）
  ├─ 切换仓库（主仓库 WH01 / 其他）
  ├─ 点击状态卡（就绪 / 今日已完成 / 逾期 / 已取消）
  │     └─ 列表页：固定该状态，顶部用「作业类型」二次筛选
  ├─ 点击作业类型卡（OUT/IN/PC/SFP/INT）
  │     └─ 列表页：固定该类型，顶部用「状态」二次筛选
  │           └─ 点击列表行 → 打开现有扫码页（action 690 + wiz_id）
  ├─ IA 库存调整（独立分支）
  │     └─ 进入 stock.quant 盘点扫码（参考 qz_scanner，不建 picking type）
  ├─ 点击最近作业
  │     ├─ 未完成 → 打开现有扫码页
  │     └─ 已完成/已取消 → 打开单据表单（待确认）
  ├─ 扫码框（单据号 / 产品条码 / 库位码）
  │     └─ 定位唯一单据 → 扫码页；多个 → 候选选择；无 → 提示
  └─ 返回上一页 / 库存菜单
```

现有扫码页（`PickingScanApp`）的扫码规则、数量写入、超量策略、包装逻辑全部保持不变，工作台只负责“选单/入口”。

## 8.3 页面结构（按 Pixso `52:5192`）

| 区域 | 内容 | 设计要点 |
|---|---|---|
| 品牌条 | `BY ODOO` | 粉色 `#FF4D97` 底、黑色文字；已确认保留 |
| 标题 | `扫码工作台` + 副标题 `库存扫码 · 作业入口` | 大标题黑色 900；副标题灰色 |
| 扫码行 | 返回、扫码输入框、相机；齿轮暂不显示 | 与现有扫码页同规格（38px 高、白底黑边、黄相机键）；列表页无齿轮，改为漏斗筛选按钮（见 §8.3.1） |
| 仓库条 | `主仓库 WH01` + 下拉箭头；右侧 `张明 · 09:42` | 工作台为扫码行下方的整条黄色栏；列表页改为右上角黄色按钮（见 §8.3.1） |
| 状态卡 | 状态区标题 `状态`；9 张卡：所有/就绪/今日已完成/逾期/已取消/草稿/等待/等待其他作业/进行中 | 手机首屏 4 张横向滑动；≥768px 9 张一行铺满；点击进入对应列表页 |
| 作业类型 | OUT 交货单 / PC 拣取组件 / IN 收据 / SFP 存储成品 / INT 内部调拨 / IA 库存调整 | 两列卡片；每张带彩色标题带、英文副标题、右下粉色数量徽标；点击进入对应列表页，IA 进盘点 |
| 最近作业 | 3 行单据 + 分页 `1-80 / 353` | 每行：星标（原生 `priority`）、单据号、状态徽标、来源单号/往来单位、日期；分页在区块右上与页面底部各一处，无“查看全部” |
| 底部提示 | `扫描单据号 / 产品条码 / 库位码` | 灰色小字，居中 |

补充：

- 颜色沿用现有扫码页 token：背景 `#F7F3E8`、卡片 `#FFFFFF`、黄 `#FFE500`、蓝 `#4361EE`、绿 `#00D97E`、粉 `#FF4D97`、橙 `#FF6B2C`、黑 `#111111`、次要文字 `#555555`、分隔 `#BBB6A6`。
- 状态卡：就绪=蓝、今日已完成=绿、逾期=粉、已取消=红。
- 作业类型标题带颜色：OUT 绿、PC 灰、IN 蓝、SFP 粉、INT 黄、IA 橙；具体值以 Pixso 节点为准。
- 响应式（2026-11-19 追加）：
  - 状态区：手机一屏显示 4 张、其余 5 张横向滑动；≥768px 显示全部 9 张，等宽铺满一行。
  - 作业类型：手机 2 列；≥768px 6 列，一行显示完。
  - 作业列表（最近作业与列表页）：手机 1 列；≥768px 2 列。
  - 页面整体最大宽度 1000px 居中。
- 暗色模式按 Pixso Dark 变量同步。

### 8.3.1 列表页（两个入口，Pixso `52:8364` / `52:8352`）

两个入口共用一个列表页组件，只是标题和顶部筛选维度不同：

| 入口 | 标题 | 副标题 | 顶部筛选 | 设计 frame |
|---|---|---|---|---|
| 点击工作台状态卡（如「就绪」） | 就绪 | 就绪单据 · 作业入口 | **作业类型**横排：所有 + 各作业类型卡（带数量） | `52:8364`「从就续进来」 |
| 点击工作台作业类型卡（如「收据」） | 收据 | 收货 · 作业入口 | **状态**横排：所有 + 就绪/今日已完成/逾期/已取消/草稿/等待/等待其他作业/进行中 | `52:8352`「从作业类型进来」 |

列表页细节（以 2026-11-19 更新后的设计为准）：

- 顶部右侧是黄色「主仓库 WH01 ▼」短按钮，去掉用户名（工作台仍显示 `张明 · 09:42`）。
- 标题下方是一条扫码行：白色返回按钮、扫码输入框、黄色相机按钮、右侧白色漏斗（筛选）按钮；与工作台扫码行同规格，全部 2px 黑边 + 硬阴影。
- 漏斗按钮打开 Odoo 原生 `stock.picking` 搜索/筛选面板（见 §8.5.2），用于上方筛选卡覆盖不到的条件。
- 筛选区上方有小标题「作业类型」或「状态」。
- 筛选卡：手机/窄屏约 80×60，2px 黑边 + 4/4 硬阴影，横向滚动；「作业类型 / 状态」标题右侧提供 `<` `>` 按钮，鼠标用户无需拖拽即可翻看；≥768px 卡片等宽铺满整行，无溢出时自动隐藏箭头。
- 筛选卡颜色：「所有」黑底白字，具体项使用对应状态/类型颜色，底部显示数量；数量为 0 也显示 `0`。
- 状态筛选共 9 项，首屏优先显示「所有/就绪/今日已完成/逾期」，其余可手指左右拖动查看；类型筛选同理横向滚动。
- 列表行：白卡、2px 黑边、4/4 硬阴影；按下/选中 → 橙色边 + 整卡右下位移 4px + 去掉阴影（与产品卡一致）。
- 行内容：
  - 第一行：星标（Odoo 原生 `priority`，可点击切换=收藏/紧急）、单据号、状态徽标（草稿/就绪/逾期/已取消/等待其他作业…）。
  - 第二行：来源单号（如 `P01261`，对应 `origin`）、往来单位（如「三星」，对应 `partner_id.name`）；右下日期（如 `10月29日`）。
- 分页：`1-80 / 353` + 左右箭头；每页 80；筛选变化回到第 1 页；单页/无数据时箭头禁用。
- 底部提示：`点击单据查看详情或直接扫码`。
- 列表页没有黑色页尾，分页与提示直接放在页面底部。

交叉筛选规则：

- 状态页：标题固定为状态（如「就绪」），作业类型卡的数量 = 该状态下各类型的单据数；「所有」= 该状态总数。
- 类型页：标题固定为类型（如「收据」），状态卡的数量 = 该类型下各状态的单据数；「所有」= 该类型总数。
- 只保留一个筛选维度：状态页只能再选作业类型，类型页只能再选状态；要换另一维度需返回上一页重选（已确认）。
- 切换筛选只刷新列表与分页，不改变页面标题；切换仓库**不重置**筛选（已确认），只刷新数量与列表。

### 8.3.2 状态颜色与 Odoo 状态映射（已确认：只用 Odoo 原生状态）

Odoo 19 `stock.picking.state` 原生只有 6 个值（`stock/models/stock_picking.py#L575-L589`）：

| 原生值 | Odoo 文案 | 中文常用译法 |
|---|---|---|
| `draft` | Draft | 草稿 |
| `waiting` | Waiting Another Operation | 等待其他作业 |
| `confirmed` | Waiting | 等待 |
| `assigned` | Ready | 就绪 |
| `done` | Done | 已完成 |
| `cancel` | Cancelled | 已取消 |

工作台的 9 个筛选卡是「6 个原生状态 + 3 个派生筛选」，**不新增、不删除任何 state 值**：

| 设计状态 | 颜色 token | 白天 / 暗色 | 实际筛选条件 |
|---|---|---|---|
| 所有 | 描边/主 | `#111111` / `#E6EDF7` | 不过滤 |
| 就绪 | 强调/蓝 | `#4361EE` / `#4D7CFF` | `state = assigned` |
| 今日已完成 | 强调/绿 | `#00D97E` / `#00E5A0` | `state = done` 且 `date_done` 在用户时区今天 |
| 逾期 | 强调/品红 | `#FF4D97` / `#FF4D97` | 复用 Odoo 原生 Late 域：`state in (assigned, waiting, confirmed)` 且 `has_deadline_issue or date_deadline < today or scheduled_date < today` |
| 已取消 | 强调/红 | `#C03636` / `#C03636` | `state = cancel` |
| 草稿 | 描边/弱 | `#BBB6A6` / `#5A6878` | `state = draft` |
| 等待 | 强调/橙 | `#FF6B2C` / `#FF8A3D` | `state = confirmed` |
| 等待其他作业 | 强调/橙 | `#FF6B2C` / `#FF8A3D` | `state = waiting` |
| 进行中 | 强调/荧光 | `#FFE500` / `#C8FF3D` | 派生：`state = assigned` 且已有拣货数量（`move_line_ids.quantity > 0`）；如不接受派生条件则去掉该卡 |

> 「进行中」不是 Odoo 原生状态，只能作为 `assigned` 的细分筛选；不新增 state 值。其余 8 项均直接对应原生状态或原生 Late 条件。

## 8.4 数据口径（已确认部分 + 待确认项）

| 指标 | 口径 | 状态 |
|---|---|---|
| 仓库切换 | `stock.warehouse` 中当前用户可访问的仓库；默认上次选择（存 `res.users`），其次用户公司默认仓库 | 已确认（Q3） |
| 用户负责范围 | `stock.picking.type.favorite_user_ids` 包含当前用户的作业类型；无收藏时回退该仓库全部活动类型 | 已确认（Q2 按默认） |
| 就绪 | `stock.picking.state = assigned`，限定所选仓库 + 负责类型 | 已确认（Q4） |
| 今日已完成 | `state = done` 且 `date_done` 落在用户时区的今天 00:00–24:00；不含取消 | 已确认（Q5） |
| 逾期 | 复用 Odoo 原生 Late 域（`has_deadline_issue` 或 `date_deadline`/`scheduled_date` 已过），状态 `assigned/waiting/confirmed` | 已确认（Q6，见 §8.9 说明） |
| 作业类型数量 | 该类型下未完成单据数（`confirmed/waiting/assigned`）；0 也显示 | 已确认（Q7/Q17） |
| 最近作业 | 新增“用户最近访问”模型：`user_id + picking_id + last_seen`，按 `last_seen desc` 分页（页大小同列表） | 已确认（Q10） |
| 今日/逾期时区 | 用户 `tz`，服务端按 UTC 存储、按用户时区计算边界 | 已确认 |

### 8.4.1 用户“负责”的定义（已确认）

选 **1 作业类型收藏**：`stock.picking.type.favorite_user_ids`。用户在作业类型上收藏自己负责的类型；工作台只统计这些类型。无收藏时回退该仓库全部活动类型。

### 8.4.2 最近作业的“最后操作日期”（已确认）

- 采用方案 A：打开扫码页时更新 `last_seen`，列表显示“最后访问日期”。
- 每个用户最多保留 30 条，超出清理更早记录；不再提供「查看全部」。

## 8.5 交互细节（已确认部分 + 待确认项）

### 8.5.1 工作台

| 操作 | 行为 | 状态 |
|---|---|---|
| 点击作业类型卡 | 打开该类型列表页（§8.3.1），顶部为状态筛选 | 已确认（Q9） |
| 点击最近作业 | 未完成 → 扫码页；已完成/取消 → 单据表单 | 已确认（Q11 按默认） |
| `查看全部 →` | 设计已去掉，不再提供 | 已确认（Q10） |
| 点击状态卡 | 就绪/今日已完成/逾期/已取消 → 对应列表页 | 已确认（Q13） |
| 扫码框 | 单据号 → 唯一则进扫码页，多条弹候选；产品条码/库位码 → 查匹配的待处理单，多条弹候选 | 已确认（Q12） |
| 未知条码 | 红色提示 + 错误音，不跳转 | 已确认 |
| 相机 | 调起相机扫码，与扫码枪同一处理 | 已确认 |
| 齿轮 | 暂不显示（功能待定）；列表页没有齿轮，右侧是漏斗筛选按钮 | 已确认（Q25） |
| 下拉刷新 | 不做（设计未画入口） | 已确认 |
| 返回 | 返回上一页/库存菜单 | 已确认 |
| 右侧 `张明 · 09:42` | 当前用户 + 当前时间（列表页不显示） | 已确认（Q20） |
| 卡片按下 | 状态卡/类型卡/最近作业行：整卡右下位移 4px + 去掉硬阴影，松手复原 | 已确认 |

### 8.5.2 列表页（2026-11-19 更新设计）

| 操作 | 行为 | 状态 |
|---|---|---|
| 顶部筛选卡点击 | 只刷新列表与分页，不重建页面；选中卡按下位移 4px + 去阴影 | 已确认 |
| 筛选项范围 | 状态 9 项、首屏优先 4 项（所有/就绪/今日已完成/逾期），其余手指左右拖动；类型筛选项同理 | 已确认（Q16） |
| 数量为 0 | 仍显示 `0`，点击后列表清空显示空状态（不弹右上角提示） | 已确认（Q17，2026-11-20 去掉提示框） |
| 二次筛选 | 只保留一个维度：状态页只能选作业类型，类型页只能选状态；换维度需返回上一页 | 已确认（Q17） |
| 列表行点击 | 整行可点（星标除外）→ 打开现有扫码页（action 690 + wiz_id） | 已确认 |
| 列表行按下 | 2px 黑边 + 4/4 硬阴影；按下/选中 → 橙色边 + 整卡右下位移 4px + 去阴影 | 已确认 |
| 星标 | 复用 Odoo 原生 `stock.picking.priority`（`priority = 1`，与原生「Starred」筛选同口径），点击切换，不新建模型 | 已确认（Q18） |
| 分页 | 每页 80（与 Odoo 列表默认一致），`1-80 / 353`，仅上一页/下一页；筛选变化回第 1 页；首/末页禁用 | 已确认（Q24） |
| 顶部仓库按钮 | 黄色短按钮，不显示用户名；切换仓库**不重置**筛选，只刷新数量与列表 | 已确认（Q20） |
| 扫码框 | 设计已包含：白色返回 + 扫码输入框 + 黄色相机 + 白色漏斗；扫单据号直接打开扫码页，产品/库位多单弹候选 | 已确认（Q21） |
| 漏斗按钮 | 打开 Odoo 原生筛选（方案 A，见 §8.6.5），与上方筛选卡叠加使用 | 已确认（Q27） |
| 空状态 | 无数据时显示空状态文案 + 返回；分页 `0 / 0`，箭头禁用 | 已确认 |
| 返回 | 回到工作台，保留此前仓库与筛选状态 | 已确认 |

## 8.6 技术方案（确认后实施）

### 8.6.1 前端

- 新增客户端动作 `stock_barcodes_picking.action_scan_workbench`，tag `stock_barcodes_picking.ScanWorkbench`，`target=fullscreen`。
- 新增 OWL 组件 `ScanWorkbench`：
  - `static/src/workbench/scan_workbench.js`
  - `static/src/workbench/scan_workbench.xml`
  - `static/src/workbench/scan_workbench.scss`
  - 复用现有图标与颜色 token；深色模式同步。
- 工作台不写业务逻辑；只调用后端服务方法、渲染数据、跳转扫码页。
- 工作台与列表页放在同一个客户端动作内，用组件状态切换（`view = "workbench" | "list"`），保留 `warehouse`、`dimension`、`value`、`filter`、`page`，并支持浏览器返回；不新增第二个客户端动作。
- 列表页复用工作台的品牌条、标题、扫码行（返回/输入/相机/漏斗）；筛选卡、列表行沿用现有 `o_scan_row` 的 4px 位移 + 去阴影规则。
- 进入扫码页时复用 `stock.picking.action_barcode_scan`（创建 `wiz.stock.barcodes.picking` 并返回 action 690），不复制扫码逻辑。
- 入口替换：`stock.picking` list/kanban 头部按钮（0 选中）改为打开工作台；行内按钮继续进入单张单据。action 690 在无 `wiz_id` 时也重定向到工作台，兼容旧 URL。

### 8.6.2 后端

新增 `stock.barcodes.workbench`（`_auto = False` 的服务模型）或在现有 wizard 上增加方法，建议独立服务模型：

```text
get_workbench_data(warehouse_id=None)
  → {user, warehouses, selected_warehouse, stats, types[], recent[]}

get_workbench_list(warehouse_id, dimension, value, filter_value=None, page=1, page_size=80)
  → {total, page, page_size, records[], facets{}, warehouse}
  # dimension = "status" | "type"
  # 状态入口：value=status，facets 返回该状态下各作业类型数量（含 0）
  # 类型入口：value=type，facets 返回该类型下各状态数量（含 0）

scan_workbench_barcode(barcode, warehouse_id)
  → {action: "open_picking" | "choose" | "error", picking_id?, candidates?, message?}

mark_recent(picking_id)
  → 更新当前用户的最近访问
```

- `get_workbench_data` / `get_workbench_list` 用 `read_group`/SQL 聚合，避免逐类型查询；所有统计加“所选仓库 + 负责类型”域。
- 列表分页用 `search_count` + `search(..., limit=page_size, offset=(page-1)*page_size)`；排序复用 Odoo 原生口径：`priority desc, scheduled_date asc, id desc`。
- 列表行返回字段：`id, name, state, origin, partner_id, picking_type_id, priority, scheduled_date, date_deadline, date_done`，由前端决定显示来源单号/往来单位/日期。
- 统计遵守记录规则：用 `with_user(env.user)`；如用 `sudo()`，必须显式加仓库/类型/公司域。
- 逾期域直接复用 `stock.picking` 原生搜索视图的 Late 条件（`stock/views/stock_picking_views.xml` `filter name="late"`），避免口径分裂。
- 新增最近访问模型：

```text
stock.barcodes.picking.recent
  user_id      Many2one res.users (required, index)
  picking_id   Many2one stock.picking (required, index, ondelete=cascade)
  last_seen    Datetime (required, index, default=now)
  unique(user_id, picking_id)
```

- 保留策略：每个用户最多保留 30 条；每次 `mark_recent` 清理更早记录。
- 权限：`stock.group_stock_user` 可读/写自己的最近记录；记录规则 `user_id = uid`；工作台动作对库存用户开放。
- 仓库切换持久化：在 `res.users` 增加 `barcode_workbench_warehouse_id`（跨设备；卸载时列与数据自动删除）。
- 入口替换：
  - 方案 A：新增工作台动作 + 菜单/快捷方式改为新动作；action 690 继续只做扫码页。
  - 方案 B（推荐）：`stock.picking` list/kanban 头部按钮（0 选中）打开工作台；action 690 在 `wiz_id` 为空时重定向到工作台，旧 URL 继续可用。
  - 方案 C：修改 action 265（会影响原生 To Do 列表，不推荐）。

### 8.6.3 IA 库存盘点（已确认：完整实现扫码盘点）

参考 `/run/media/max/DATA1/projects/odoo-dev/19.0/addons/qz_scanner/qz_stock_scanner` 的盘点实现，结论：

- qz_scanner **没有为盘点新建 `stock.picking.type`**，而是直接操作 `stock.quant` 的盘点模式：
  - [stock_quant.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/qz_scanner/qz_stock_scanner/models/stock_quant.py#L10-L95) 的 `get_scanner_inventory_data()` 按仓库库位加载待盘点 quant；
  - 应用盘点用 `with_context(inventory_mode=True)` + `action_apply_inventory()`；
  - 独立客户端动作 `qz_stock_inventory`，在扫码首页作为独立菜单项。
- 本模块 **IA 卡进入完整的扫码盘点页面**（不是只做跳转），并保持同一套野兽主题样式。

#### 盘点页面范围

| 区域 | 内容 |
|---|---|
| 顶部 | 返回、扫码输入框、相机；标题「库存盘点」+ 副标题「按产品 / 库位 / 批次扫码盘点」 |
| 仓库 | 与工作台同步当前仓库；切换后重新加载待盘点行 |
| 盘点行 | 产品名、库位、批次/序列号、账面数量、实盘数量（可编辑）、差异（正绿负粉） |
| 扫码行为 | 产品条码/批次/序列号/库位条码 → 定位对应 quant；唯一直接聚焦实盘数量，多条弹候选 |
| 底部 | 「应用盘点」按钮；未填写实盘数量时禁用；应用成功后提示并保留当前仓库、刷新待盘点数 |

#### 后端接口

```text
get_inventory_scan_data(warehouse_id, barcode=None)
  → {quants: [{id, product, location, lot, quantity, inventory_quantity, diff}], pending_count}

scan_inventory_barcode(barcode, warehouse_id)
  → {action: "focus" | "choose" | "error", quant_id?, candidates?, message?}

set_inventory_quantity(quant_id, inventory_quantity)
  → 仅写内存/前端状态，或直接写 quant.inventory_quantity（inventory_mode）

apply_inventory(quant_ids)
  → with_context(inventory_mode=True).action_apply_inventory()
```

- 待盘点口径与 qz_scanner 一致：所选仓库内部库位中 `inventory_date <= today` 的 quant 行数，作为工作台 IA 卡数量。
- 只允许操作所选仓库的内部库位；`with_user(env.user)`，跨公司/跨仓库拒绝。
- 不新增 `stock.quant` 字段、不新建盘点模型；盘点产生的库存调整走 Odoo 原生 `stock.move`/`stock.quant`，卸载模块后这些属于正常业务数据，不视为残留。
- 盘点权限：`stock.group_stock_user`。

其余缺口：

- 作业类型的英文副标题（OUTBOUND/PICKING/STOCK FINISHED GOODS 等）与标题带颜色，建议在 `stock.picking.type` 增加工作台展示字段（`barcode_workbench_label`、`barcode_workbench_subtitle`、`barcode_workbench_color`），否则只能按 `sequence_code` 硬编码。
- 设计中状态卡/类型卡的数量是示意值（含 `353`、`500`），当前库单据量远小于此，需要真实口径后才能验证。

### 8.6.4 卸载无数据残留（硬性要求）

目标：卸载 `stock_barcodes_picking` 后，数据库不留下本模块产生的表、列、视图、XML 数据、配置参数或运行期记录。

已核实的 Odoo 19 卸载机制：

| 机制 | 代码位置 | 效果 |
|---|---|---|
| 删除模型表 | [`_drop_table()`](file:///run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo/addons/base/models/ir_model.py#L333-L345) 与 [`ir.model.unlink()`](file:///run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo/addons/base/models/ir_model.py#L362-L381) | 删除本模块定义模型的物理表/视图（`DROP TABLE ... CASCADE` / `DROP VIEW`） |
| 删除新增列与列内数据 | [`_drop_column()`](file:///run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo/addons/base/models/ir_model.py#L864-L883) 与 [`ir.model.fields.unlink()`](file:///run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo/addons/base/models/ir_model.py#L988-L1013) | 删除本模块给核心模型新增的列：`ALTER TABLE ... DROP COLUMN ... CASCADE`，**列里的数据随列一起删除**（回答 Q23：会给 `stock.picking.type`、`res.users` 新增列，卸载时字段与数据一并删除） |
| 删除 XML 数据 | [`_module_data_uninstall()`](file:///run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo/addons/base/models/ir_model.py#L2464-L2612) | 删除带 xmlid 的 action/view/access/config 参数等记录 |

由此确定的实现约束：

- 最近访问等持久化数据必须建成正常 ORM 模型（`_auto=True`），卸载时自动删表，不写手工 SQL。
- 给核心模型新增的展示字段（标签/副标题/颜色）和用户偏好字段（上次仓库）会被自动删列，数据随列删除。
- 服务模型 `stock.barcodes.workbench` 使用 `_auto=False` 且不建表，卸载只删除 `ir.model` 元数据。

必须补的缺口（现状已存在）：

1. [ir_config_parameter.xml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/data/ir_config_parameter.xml) 用 `<function>` 写入 `barcode.max_time_between_keys_in_ms=1500`，**不产生 xmlid**，卸载后不会自动删除。
   - 方案：`post_init_hook` 把写入前的原值备份到模块自有参数（如 `stock_barcodes_picking.barcode_max_time_backup`，不存在则记空）；`uninstall_hook` 恢复原值，原先不存在则删除该 key，同时删除备份参数。
   - 不能无条件删除：该 key 属于 `barcodes` 依赖，可能已被管理员或其他模块修改。
2. 运行期写入核心模型的无 xmlid 记录（`mail.message`、`ir.attachment`、`bus.bus`、`ir.logging`）不随卸载删除。本方案不使用这些模型；若后续新增，必须写进 `uninstall_hook`。
3. 不在 SQL 中手工建表/视图/触发器/序列；如必须，`uninstall_hook` 中显式 DROP。
4. 浏览器 localStorage 不属于数据库，不构成 DB 残留；但换设备或清缓存会丢失，需要跨设备时改用 `res.users` 字段。

交付要求：

- `__manifest__.py` 增加 `"uninstall_hook": "uninstall_hook"`，在 [hooks.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/hooks.py) 实现，并对 `barcode.max_time_between_keys_in_ms` 的恢复逻辑加测试。
- 卸载验证 SQL（测试库执行，期望全部为 0 或空）：

```sql
SELECT count(*) FROM information_schema.tables
 WHERE table_name LIKE 'stock_barcodes%';
SELECT table_name, column_name FROM information_schema.columns
 WHERE column_name LIKE 'barcode_workbench%';
SELECT count(*) FROM ir_model WHERE model LIKE 'stock.barcodes%';
SELECT count(*) FROM ir_model_fields WHERE name LIKE 'barcode_workbench%';
SELECT count(*) FROM ir_model_data WHERE module = 'stock_barcodes_picking';
SELECT key FROM ir_config_parameter
 WHERE key IN ('barcode.max_time_between_keys_in_ms',
               'stock_barcodes_picking.barcode_max_time_backup');
```

- 验收链路：安装 → 使用（产生最近作业、切换仓库、改配置）→ 卸载 → 上述 SQL 无残留 → 重新安装无报错。

**实测结果（2026-11-19，P6）**

- 用 `createdb -T odoo19 odoo19_uninstall_test` 复制测试库，执行 `button_immediate_uninstall()` 后校验：
  - `stock_barcodes%` 表 0；`barcode_workbench%` 列 0；`stock.barcodes%` 模型 0；`ir_model_data(module=stock_barcodes_picking)` 0；备份参数 0。
  - `stock_picking_type.barcode_scan_*` 列仍在：它们由仍安装的 `stock_barcodes_mrp` 拥有，不是本模块残留。
  - `barcode.max_time_between_keys_in_ms` 保留：值已被管理员改为 `2500`（不是模块写入的 `1500`），按“不误删他人配置”原则保留。
- `hooks.py` 已实现 `post_init_hook`（先备份原值，仅当参数不存在时写 `1500`）与 `uninstall_hook`（有备份则恢复，无备份且仍为 `1500` 则删除）。
- 注意：`__init__.py` 必须导出 `uninstall_hook`，否则卸载时报 `has no attribute 'uninstall_hook'`。
- `data/ir_config_parameter.xml` 已删除，避免 `<function>` 写入无 xmlid 的残留。

### 8.6.5 漏斗按钮：复用 Odoo 原生筛选（可行性已确认）

结论：**可行，推荐方案 A**。

- 方案 A（推荐）：漏斗按钮打开一个 `ir.actions.act_window`（`res_model=stock.picking`，`view_mode=list,kanban,form`），domain 带上「当前仓库 + 固定状态/类型」，其余交给 Odoo 原生搜索视图。用户可继续用原生搜索、分组、收藏、Late、日期、产品、批次、包装等全部筛选，零维护，升级不易坏。
- 方案 B：在自建页面内嵌 Odoo `SearchModel` + `SearchBar`。视觉统一，但需要自己维护搜索 arch、模型生命周期，Odoo 升级风险高，不建议首期做。
- 两种方案都不改原生视图，也不新增搜索字段；筛选条件由 URL/context 传入，返回时回到自建列表页。

## 8.7 实施阶段

| 阶段 | 内容 | 产出 |
|---|---|---|
| P0 | 需求确认（已完成） | 本文件 §8.9.1 |
| P1 | 静态还原工作台 UI + 两个列表页 UI（mock 数据） | OWL 页面 + 移动/平板/桌面 + 暗色 |
| P2 | 后端聚合接口（工作台 + 列表/分面）+ 仓库切换 + 权限 | `get_workbench_data` / `get_workbench_list` + 测试 |
| P3 | 列表筛选/分页、星标、扫码跳转、漏斗原生筛选 | 列表交互 + `scan_workbench_barcode` + 最近访问模型 |
| P4 | IA 扫码盘点页 + 应用盘点 | `get_inventory_scan_data` / `scan_inventory_barcode` / `apply_inventory` + 测试 |
| P5 | 入口替换（list/kanban 头部按钮 + action 690 重定向） | 新动作 + 重定向 |
| P6 | 回归、性能、卸载清理 | 单元测试 + 手工验收 + `uninstall_hook` |

## 8.8 验收标准

- [ ] 工作台 UI 与 Pixso `52:5192` 一致：品牌条、标题、扫码行、仓库条、四状态卡、两列作业类型、最近作业、底部提示。
- [ ] 状态卡列表页与 Pixso `52:8364` 一致：标题/副标题、右上短仓库按钮、扫码行（返回/输入/相机/漏斗）、作业类型筛选卡（含 0）、列表行、分页、底部提示。
- [ ] 作业类型列表页与 Pixso `52:8352` 一致：固定类型标题、状态筛选卡、相同列表行与分页。
- [ ] 状态筛选 9 项可横向拖动，首屏优先显示 4 项；数量为 0 显示 `0`，点击只显示列表空状态（不弹右上角提示）。
- [ ] 二次筛选保持单一维度；换维度需返回上一页；切换筛选/仓库的行为与 §8.5.2 一致（仓库不重置筛选）。
- [ ] 筛选卡、列表行、状态卡、类型卡按下时整卡右下位移 4px 且去掉硬阴影；列表行选中为橙色边。
- [ ] 星标读取/写回 `stock.picking.priority`，与 Odoo 原生「Starred」筛选结果一致，不新增模型。
- [ ] 分页按 80/页显示 `x-y / total`；仅上一页/下一页；首/末页禁用；空状态正确。
- [ ] 漏斗按钮打开 Odoo 原生 `stock.picking` 筛选，domain 带当前仓库 + 固定维度，返回后回到原列表页。
- [ ] IA 卡进入完整扫码盘点页：按产品/批次/序列号/库位扫码定位 quant，支持录入实盘数量、显示差异、应用盘点。
- [ ] IA 待盘点数量 = 所选仓库内部库位 `inventory_date <= today` 的 quant 行数；应用盘点后数量刷新。
- [ ] 盘点只能操作所选仓库内部库位；跨仓库/跨公司 quant 被服务端拒绝；无权限用户不可见 IA。
- [ ] 移动端 357px、平板/桌面按确认的响应式规则显示；暗色模式正常。
- [ ] 切换仓库后，状态卡、类型数量、最近作业全部切换；选择持久化在 `res.users`。
- [ ] 就绪/今日已完成/逾期/类型数量的口径与确认结果一致，边界（跨天、时区、取消单）有测试。
- [ ] 最近作业只显示当前用户的记录，按最后访问时间倒序；点击可进入扫码页或表单。
- [ ] 扫码框（工作台与列表页）能正确进入唯一单据、候选选择或错误提示。
- [ ] 旧入口（list/kanban 头部按钮）进入工作台；行内扫码按钮仍进入单张单据。
- [ ] 只统计当前用户可访问的仓库/类型；不能看到其他公司或其他仓库数据。
- [ ] 统计接口在 1 万张单据规模下响应可接受（目标 < 500ms，按实际环境验证）。
- [ ] 新模型有访问权限、记录规则和清理策略；无孤立记录。
- [ ] 卸载后无残留：`stock_barcodes%` 表、`barcode_workbench%` 列、`stock.barcodes%` 模型、`ir_model_data`、相关 `ir_config_parameter` 全部为空；重装无报错（见 §8.6.4 验证 SQL）。

## 8.9 已确认结论与剩余待确认问题

### 8.9.1 已确认（2026-11-19 回复）

| 编号 | 结论 |
|---|---|
| Q1 | 原入口是单据 list/看板头部的扫码按钮（0 选中 → 扫码优先）；新工作台替换该入口，行内按钮保留 |
| Q2 | 按默认：`favorite_user_ids` 作业类型收藏；无收藏回退该仓库全部活动类型 |
| Q3 | 上次选择，存 `res.users` 字段；无则公司默认仓库 |
| Q4 | 就绪 = `assigned` |
| Q5 | 今日已完成 = `done` 且 `date_done` 用户时区今天，不含取消 |
| Q6 | 逾期复用 Odoo 原生 Late 域（见下方说明） |
| Q7 | 未完成单据数；0 也显示 |
| Q8 | IA 走 `stock.quant` 盘点入口，不建 picking type（参考 qz_scanner） |
| Q9 | 点击作业类型卡进入新增列表页 |
| Q10 | 打开扫码页时更新最近访问；最多 30 条；去掉「查看全部」 |
| Q11 | 未完成进扫码页、已完成/取消进表单；列表行同规则 |
| Q12 | 单据号/产品条码/库位码都支持；多张单弹候选 |
| Q13 | 状态卡可点击进入列表页 |
| Q14 | 保留 `BY ODOO` 品牌条；右侧显示当前用户 + 时间；最大宽度 1000px 居中 |
| Q15 | 库存用户可见；仓库按用户可访问公司过滤 |
| Q16 | 状态筛选放 9 个，首屏优先 4 个，其余横向拖动；只用 Odoo 原生状态，不新增/删除 state 值 |
| Q17 | 只用一个筛选维度；数量 0 显示 `0`，点击只看空列表（2026-11-20：去掉右上角提示框） |
| Q18 | 复用 Odoo 原生 `priority` 星标（`priority=1`），不新建模型 |
| Q19 | 仅上一页/下一页；每页 80 |
| Q20 | 列表页与工作台都用黄色仓库按钮，列表页缩短并去掉用户名；切仓库不重置筛选 |
| Q21 | 列表页保留扫码框（设计已包含） |
| Q22 | 按 Odoo 现有拣货单取值：`name / origin / partner_id / scheduled_date / date_done / priority`，不另造字段 |
| Q23 | 最近访问用模块自有模型；上次仓库用 `res.users` 字段；确认新增字段的数据会随列一起删除 |
| Q24 | 每页 80，分页文案 `1-80 / xxx` |
| Q25 | 工作台齿轮暂不显示（功能未定）；列表页没有齿轮，改为漏斗筛选按钮 |
| Q26 | IA 完整实现扫码盘点（`stock.quant` 盘点模式），不是只做跳转 |
| Q27 | 漏斗采用方案 A：打开 Odoo 原生 `stock.picking` 筛选列表 |

### 8.9.2 Q6 说明：`date_deadline` 与 `scheduled_date` 的区别

| 字段 | 含义 | 来源 | 适合判断 |
|---|---|---|---|
| `scheduled_date`（Scheduled Date） | 这张调拨单**计划什么时候开始作业** | 由 `move.date` 汇总，默认当前时间，可手动改 | 排程、按日期分组、“计划时间已过” |
| `date_deadline`（Deadline） | 对客户/供应商的**承诺截止时间** | 由 `move.date_deadline` 汇总（销售承诺交付日 / 采购承诺到货日） | 是否延误、是否影响交付承诺 |

Odoo 原生 Late 筛选同时比较两者：`has_deadline_issue` 或 `date_deadline < today` 或 `scheduled_date < today`。因此本模块的「逾期」直接复用原生 Late 域，不单独二选一。

### 8.9.3 剩余待确认

本轮阻塞问题已全部确认，无剩余阻塞项。仅保留两项非阻塞细节，可实施中再定：

1. **工作台齿轮的具体功能**：当前暂不显示；后续想好后补入口即可，不影响编码。
2. **工作台下拉刷新**：设计没有画刷新入口，默认不做；若需要可后续加。

## 8.10 默认值与确认结果

Q1–Q27 均已确认，直接采用 §8.9.1 的结论，无需再取默认值。

## 8.11 本次变更记录（2026-11-19）

- 设计更新：列表页增加扫码行（返回/输入/相机/漏斗）、右上短仓库按钮、筛选区小标题。
- 状态口径：只使用 Odoo 原生 6 个 state；9 个筛选卡 = 6 原生 + 3 派生（今日已完成/逾期/进行中）。
- 二次筛选确认单维度；0 数量显示空列表（无提示框）；切仓库不重置筛选。
- 星标复用原生 `priority`；IA 参考 qz_scanner 走 `stock.quant`，不建 picking type，并确认完整实现扫码盘点。
- 新增 §8.6.4 卸载无残留（已核实新增字段的数据会随列删除）与 §8.6.5 原生筛选可行性。
- 分页 80/页；Q24–Q27 已全部确认，可进入 P1。

**2026-11-20 工作台主页对齐新设计**

- 状态区保留全部 9 张卡（横向滚动、箭头翻页）；移动端优先顺序：所有 / 就绪 / 今日已完成 / 进行中，其后为草稿/等待/等待其他作业/逾期/已取消。颜色：所有 = ink 底 + page 字、就绪 = 湖蓝 `#1DA1B7`、今日已完成 = 绿、进行中 = 桔黄 `#FFAB00`；新增 `--wb-teal` / `--wb-amber`，`--wb-red` 统一为 `#DB3847`。
- 作业类型卡改为「彩色带显示英文代号（OUT/PC/IN/SFP/INT/IA/BATCH） + 下方中文名」；带色：OUT 绿、PC 描边灰、IN 蓝、SFP 品红、INT 荧光黄、IA 橙、BATCH 红；文字按对比取黑/白。
- 最近作业（及列表行）在原有黑色边框**内部**增加 3px 类型色条（`::before`），边框颜色不变；颜色与类型带一致（`_serialize_picking` 新增 `type_color` / `type_code`）。BATCH 类型带改为红色，规则放在主模块 SCSS，工作台主页与批量页都生效。
- 工作台右上只保留「刷新」黄色方块按钮；左上角返回箭头改为九宫格按钮，点击回功能选择页：有 `web_responsive` 时先置用户 `is_redirect_home=True` 再跳 `/odoo`（显示应用网格），否则尝试打开应用下拉菜单，兜底 `/odoo`。
- 计数核对（当前库）：所有 22（草稿 8 + 等待 1 + 等待其他作业 3 + 就绪 9 + 今日已完成 0 + 已取消 1）、就绪 9、今日已完成 0、进行中 9；就绪与进行中按 Odoo 状态天然重叠（进行中 = assigned 且已拣 > 0）。
- **返回主页后偶发卡死修复**：主页是整页跳转（`/odoo`），浏览器后退可能从 bfcache 恢复全屏 client action，旧定时器/bus 连接已失效 → 页面看似卡死。工作台、批量工作台、扫码页统一加 `pageshow`：`event.persisted` 时强制 `location.reload()`，并在挂载时清掉残留的 `o_apps_menu_opened`。

## 8.12 实施进度

### P1 静态 UI（已完成）

新增文件：

- [scan_workbench.js](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/static/src/workbench/scan_workbench.js)：OWL 组件、mock 数据、工作台/列表视图切换、筛选/分页/星标/返回。
- [scan_workbench.xml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/static/src/workbench/scan_workbench.xml)：工作台、列表页、列表行子模板。
- [scan_workbench.scss](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/static/src/workbench/scan_workbench.scss) / [scan_workbench.dark.scss](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/static/src/workbench/scan_workbench.dark.scss)：野兽主题 token、卡片、按下位移/去阴影、暗色覆盖。
- 客户端动作 `stock_barcodes_picking.action_scan_workbench`（`data/ir_actions_client.xml`），可通过 `/odoo/action-stock_barcodes_picking.action_scan_workbench` 预览。
- `__manifest__.py` 已注册 3 个前端资源与暗色样式。

已实现并自测：

- 工作台：品牌条、标题、扫码行（无齿轮）、黄色仓库条、`状态` 标题 + 9 张状态卡（手机 4 张可见可滑动，≥768px 9 张一行）、6 类型卡（手机 2 列 / ≥768px 6 列）、最近作业 + 分页、底部提示。
- 列表页：标题/副标题、短仓库按钮、扫码行（返回/输入/相机/漏斗）、9 状态筛选横向滚动（首屏 4 个）、列表行（手机 1 列 / ≥768px 2 列）、0 数量空状态、80/页分页、返回。
- 交互：筛选切换、星标填充/取消、行点击提示、翻页、返回、仓库下拉均为本地 mock 行为，无服务端调用。
- 横向滑动兼容鼠标：状态条与列表筛选条在溢出时显示 `<` `>` 按钮，按容器宽度滚动；无溢出自动隐藏。
- 列表页筛选卡：手机 80px 固定宽横向滚动；≥768px 等宽铺满整行。
- 浏览器验证：手机宽（4 卡可见 + 箭头可翻页、类型 2 列、列表 1 列）与桌面宽（9 卡一行、类型 6 列、列表 2 列、筛选卡铺满）均通过；星标、行点击、筛选、翻页、返回无客户端错误。

### P2 后端聚合 + 真实数据（已完成）

新增文件：

- [stock_barcodes_workbench.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/models/stock_barcodes_workbench.py)：`stock.barcodes.workbench` 服务模型（`_auto=False`，无表），提供 `get_workbench_data` / `get_workbench_list` / `select_warehouse` / `toggle_star` / `mark_recent`。
- [stock_barcodes_picking_recent.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/models/stock_barcodes_picking_recent.py)：最近访问模型（user + picking + last_seen，唯一约束）。
- [res_users.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/models/res_users.py)：`barcode_workbench_warehouse_id` 上次仓库。
- [stock_barcodes_picking_rules.xml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes_picking/security/stock_barcodes_picking_rules.xml)：最近访问仅本人可见/可写；ACL 已补两个模型。

实现口径：

- 状态域按 §8.3.2：`all / draft / confirmed / waiting_other / ready / done_today / overdue（原生 Late）/ cancel / ongoing`。
- 类型限定为设计中的 5 个真实作业类型（OUT/PC/IN/SFP/INT）+ IA 虚拟卡；Manufacturing / Repairs 等未映射类型不显示。
- IA 卡为虚拟入口，数量 = 所选仓库内部库位 `inventory_date <= today` 的 quant 行数；点击暂提示 P4 实现。
- 列表分页 80/页，返回 `domain` 供漏斗打开原生 `stock.picking` 筛选列表。
- 最近访问最多 30 条；打开单据时写入，卸载时随表删除。
- 星标直接写 `stock.picking.priority`，刷新后保持。

前端已接真实数据：

- 工作台统计、类型数量、用户/时间、仓库名、最近作业全部来自 RPC。
- 列表标题/副标题、筛选数量、分页、行数据来自 `get_workbench_list`。
- 行点击：未完成 → 现有扫码页；已完成/已取消 → 单据表单；同时写入最近访问。
- 仓库切换写 `res.users`，列表页保持当前筛选并刷新。
- 漏斗按钮打开原生 `stock.picking` 列表（domain 为当前筛选）。

浏览器验证：

- 工作台真实数量 所有 15 / 就绪 10 / 逾期 13，6 张设计类型卡；最近作业初始为空。
- 收据列表 6 行真实 `WH/IN/...`；逾期筛选命中 6 行；分页正确。
- 点击行打开扫码页 `WH/IN/00012`；返回后最近作业出现该单并持久化；星标刷新后保持。
- 漏斗打开原生收据列表无报错；仓库下拉可开合。

### P3 / P5 / P6（已完成）

- **P3 扫码定位**：新增 `scan_workbench_barcode`，支持单据号（精确→模糊）、库位条码、产品条码；唯一单据直接打开扫码页，多张弹 `SelectCreateDialog` 候选，未知条码中文错误提示不跳转。工作台扫码框与相机均已接入。
- **P5 入口替换**：
  - `stock.picking` list/kanban 头部条码按钮在 0 选中时打开工作台；行内按钮仍进入单张单据扫码页。
  - 直接访问 action 690（无 `wiz_id`）自动跳转工作台。
  - 浏览器验证：action-690 → 工作台；action-265 头部按钮 → 工作台；行内扫码 → 对应单据扫码页。
- **P6 卸载清理**：
  - `hooks.py` 增加 `post_init_hook` 备份 / `uninstall_hook` 恢复 `barcode.max_time_between_keys_in_ms`；`__init__.py` 导出钩子。
  - 删除 `data/ir_config_parameter.xml`（原 `<function>` 写入无 xmlid）。
  - 复制测试库实测卸载：表、工作台列、`stock.barcodes` 模型、`ir_model_data`、备份参数均无残留；其他模块拥有的字段与管理员改过的参数按预期保留（详见 §8.6.4）。

### P4 IA 扫码盘点（已完成）

- 后端新增 `get_inventory_scan_data` / `scan_inventory_barcode` / `apply_inventory`：
  - 数据范围：所选仓库内部库位 + `inventory_date <= today` 的 `stock.quant`，单次最多 500 行，另返回 `pending_count`。
  - 扫码支持产品条码、批次/序列号、库位条码；命中多行返回候选。
  - 应用盘点：仅允许本次范围内的 quant，`inventory_mode` 写入实盘数量后调用 `action_apply_inventory()`。
- 前端新增工作台第三视图「库存盘点」（沿用野兽主题）：
  - 顶部标题/短仓库按钮/扫码行（返回、输入、相机）；
  - 行显示产品、库位、批次、账面数量、实盘输入、差异（正绿负红）；
  - 扫码后按条码过滤并可「显示全部」；
  - 底部「应用盘点 (n)」按钮，未修改时禁用；应用后刷新列表与工作台 IA 数量。
- 浏览器验证（临时将 4 条 quant 的盘点日期设为今天，测试后已恢复原日期）：
  - IA 卡数量 4；页面 4 行；实盘输入 3 → 差异 +2；改回 1 → 差异 0。
  - 应用盘点成功，行从待盘点列表移除，库存数量未变（实盘=账面）。
  - 扫批次 `00000878762301112266` 过滤为 1 行，「显示全部」恢复 3 行。

### 当前状态

P1–P6 全部完成并通过验证：P1 静态 UI、P2 真实数据、P3 扫码定位、P4 IA 盘点、P5 入口替换、P6 卸载清理。

后续可选优化（非阻塞）：

- 盘点页数字键盘/扫码枪连续录入体验、盘点历史与差异报表。
- 最近作业分页（当前最多 30 条，一页展示）。
- 作业类型展示字段（标签/副标题/颜色）做成可配置，替代当前按 `sequence_code` 映射。

## 8.13 运维问题：WebSocket 未生效导致偶发卡死（2026-11-19）

现象：操作过程中偶发页面卡死。

日志证据：

- `logs/odoo.log` 中 `Couldn't bind the websocket. Is the connection opened on the evented port (8072)?` 累计 **15130** 次。
- 同日 `POST /bus/has_missed_notifications` 出现 **303** 次、单次耗时约 **600s**（长轮询兜底）。
- 实测：`ws://localhost:8071/websocket` 返回 500；`ws://localhost:8072/websocket` 可连接。
- 后端 `get_workbench_data` 实测 5–13ms、列表 2–4ms，排除新功能查询慢。

原因：

- 浏览器 bus 使用 `window.origin`（8071）拼 WebSocket 地址；8071 是 HTTP worker，WebSocket 只能由 gevent 端口 8072 提供。
- 当前没有反向代理把 `/websocket` 转到 8072，因此 WebSocket 永远失败，Odoo 退回 600s 长轮询；每次失败还会写一条完整 traceback，长期造成页面偶发无响应与日志暴涨。

修复方式：

1. 在 8071 前加 nginx（或现有网关）转发 `/websocket` 到 `127.0.0.1:8072`：

```nginx
location /websocket {
    proxy_pass http://127.0.0.1:8072;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
}
location / {
    proxy_pass http://127.0.0.1:8071;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

2. 验证：浏览器 Network 中 `/websocket` 返回 101；Odoo 日志不再出现 bind 错误。

附带修复：

- 工作台领域表达式从 `odoo.osv.expression.AND/OR` 改为 Odoo 19 的 `fields.Domain`，消除每次加载约 20 条 `DeprecationWarning` 完整堆栈日志。

---

## 9. 剩余任务与批量调拨设计（2026-11-20）

### 9.0 当前未完成任务

| 编号 | 任务 | 状态 | 阻塞点 |
|---|---|---|---|
| TODO-01 | 源库位 `internal` 限制与收货/退货冲突 | 待处理 | 需确认各业务允许的源位矩阵 |
| TODO-02 | `active_move_id` 与后台实际写入行不一致 | 待处理 | 需确认“按需求行”还是“按产品聚合” |
| TODO-03 | 同 lot 多明细 / 跨包装定位 | 包装维度已完成 | active move 颗粒度归 TODO-02 |
| TODO-04 | 删除批次/SN 的候选单守卫 | 主要项已完成 | 剩余：全模块其他写操作守卫审计；RULES 回写 |
| TODO-05 | 包装 `mandatory` 名称与生效时点 | 待处理 | 需确认“逐产品”还是“验证前全部包装” |
| — | 批次/序列号产品扫描拆包“单件+选包” | 未做 | 当前仅数量追溯产品支持 |
| — | 批量调拨（Batch Transfer） | 空单扫码已完成；批次未开始 | 桥接模块见 §9.3 |
| — | RULES.md 与历史基线回写（QTY/ACT/PACK/ISS） | 未完成 | 依赖 TODO-01/02/04/05 结论 |
| — | 自动化浏览器回归 | 未接入 | 登录态不稳定，目前靠单测 + 手工验证 |

### 9.1 现状核实

- 本模块扫码页、工作台、wizard 均只支持**单张 `stock.picking`**：`wiz.stock.barcodes.picking.picking_id` 单值，`get_scan_state` 只汇总该单。
- 工作台列表行是单选，没有多选/批量动作。
- Odoo 19 核心自带 `stock_picking_batch`（当前**未安装**）：
  - `stock.picking.batch`：`draft / in_progress / done / cancel`，`picking_ids`、`action_confirm`、`action_assign`、`action_done`。
  - 原生向导 `stock.picking.to.batch` 可把多张单加入/新建批次。
  - 批次标识就是 `name`（如 `BATCH/00001`），可直接作为扫码值，**不需要新增 barcode 字段**。

### 9.2 “批量调拨”的三种可能含义（需确认）

| 方案 | 含义 | 典型场景 | 复杂度 |
|---|---|---|---|
| A | 批量拣货：一个批次含多张待办单，按批次连续扫码并批量验证 | 一张波次拣 5 张交货单 | 中 |
| B | 批量创建：一次录入多行产品/数量，生成调拨单 | 手工补录 20 行调拨 | 中 |
| C | 批量操作：选中多张单执行确认/分配/打印/取消 | 批量确认 10 张单 | 低 |

推荐先做 **A + 轻量 C**；B 若确实需要，单独立项，避免和拣货流程混在一起。

### 9.3 推荐方案 A：接入原生批次（桥接模块）

新增独立桥接模块 `stock_barcodes_picking_batch`，`depends = ["stock_barcodes_picking", "stock_picking_batch"]`：

- 主模块不强制依赖批次模块；未安装时主模块行为完全不变。
- 批次表、字段、动作由 `stock_picking_batch` 提供，桥接模块只加交互。
- 卸载桥接模块时：其 XML/视图/向导字段自动删除，不触碰主模块与批次模块数据。

#### 工作台

- 作业类型区新增第 7 张卡「批量调拨」：数量 = 所选仓库 `draft/in_progress` 批次数；手机 2 列、≥768px 7 列。
- 新增「批量列表页」：
  - 字段：批次号、状态徽标、单据数、已完成数、负责人、计划日期。
  - 顶部状态筛选：全部 / 草稿 / 进行中 / 已完成（数量为 0 显示 0）。
  - 行点击：进入批次扫码页；星标沿用 `priority`（批次无 priority，可隐藏）。
- 新建批量入口：
  - 列表页右上「新建批量」→ 打开原生 `stock.picking.to.batch` 向导（多选待办单 → 加入/新建批次）。
  - 扫码批次号 → 直接打开该批次。

#### 批次扫码页

- 顶部显示 `BATCH/00001 · 2/5`，点击可切换单据；当前单完成后自动跳到下一张未完成单。
- 每张单**继续复用现有单 picking 扫码逻辑**，不跨单自动分配，避免写错需求行；批次只负责串联和统一验证。
- 已取消/无需求单自动跳过。
- 底部按钮：
  - 「下一单」：当前单完成或操作员手动切换。
  - 「验证批量」：全部单完成后调用 `batch.action_done()`；未完成时提示剩余单数。
- 扫码产品/批次/SN 的规则、包装、超量策略全部沿用当前单，不新增第二套规则。

#### 批量操作 C（可选）

- 列表页支持多选（复选框）→「加入批量」「确认」「分配」「打印」。
- 第一版可只做「加入批量」，其余复用原生 server action。

### 9.4 方案 B（若用户指的是“批量创建调拨”）

独立向导 `wiz.stock.barcodes.bulk.transfer`：

- 表头：作业类型、源库位、目标库位、计划日期、备注。
- 明细：产品、数量、批次/序列号、目标包（可选），支持扫码追加行。
- 生成策略二选一：
  1. 生成**一张多行**调拨单（推荐，便于统一验证）。
  2. 每行生成**一张单**（适合按行分派给不同人）。

### 9.5 数据与卸载

- 桥接模块不新增业务表；若给 `stock.picking.batch` 加展示字段，卸载时 Odoo 会删列。
- 扫码页 batch 模式给 `wiz.stock.barcodes.picking` 加 `batch_id` / `batch_picking_index`（TransientModel，自动删表）。
- 优先使用 `batch.name` 扫码，避免新增字段。
- 卸载验证沿用 §8.6.4：复制库卸载后检查表、列、`ir_model_data`、参数。

### 9.6 分阶段

| 阶段 | 内容 | 验收 |
|---|---|---|
| B-P1 | 桥接模块骨架 + 批次列表 + 工作台「批量调拨」卡 | 列表数量/状态正确，未装批次模块时主模块不受影响 |
| B-P2 | 新建批次（原生向导）+ 扫码批次号入口 | 可创建批次并进入首单 |
| B-P3 | 批次扫码模式（切换单、自动跳单、批量验证） | 完成 3 单后批次变 done |
| B-P4 | 批量操作 C（多选加入/确认/分配） | 多选动作成功 |
| B-P5 | （可选）批量创建调拨 | 按确认的生成策略落库 |
| B-P6 | 测试 + 卸载验证 + 文档 | 单张扫码流程不回退 |

### 9.7 待确认问题

| 编号 | 问题 | 建议默认 |
|---|---|---|
| B1 | A（批次拣货）/ B（批量创建）/ C（批量操作）先做哪个？ | A + 轻量 C |
| B2 | 用独立桥接模块，还是直接给主模块加 `stock_picking_batch` 依赖？ | 独立桥接模块 |
| B3 | 批次内是否允许“扫产品自动跨单分配”？ | 不允许，按当前单处理 |
| B4 | 新建批次入口：工作台多选 / 原生向导 / 扫码加单，做哪几个？ | 原生向导 + 扫码批次号 |
| B5 | 批次验证：必须全部完成才允许，还是允许部分完成生成 backorder？ | 必须全部完成 |
| B6 | 批次扫码是否保留现有包装/装箱规则（按单隔离）？ | 是 |
| B7 | 批次列表每页 30 还是 80？ | 80 |
| B8 | 是否需要方案 B（批量创建调拨）？若需要，生成一张多行还是多张单？ | 暂不做；需要则一张多行 |

### 9.8 参考 `qz_scanner` 的现有做法

对 `addons/qz_scanner/qz_stock_scanner` 的核实结论：

- **入口结构**：首页 → 作业类型看板 → 单据看板 → 全屏扫码页（`action_open_scanner`），仍是**单张 picking** 会话。
- **“批量/新建”做法**：看板上的“新建”不是多行录入，而是 `action_open_new_picking(picking_type_id)` 创建一张**空 picking** 并直接进扫码页；操作员扫产品时由 `add_product` / `_create_extra_move_line` 追加明细。
- **多单能力**：没有 `stock.picking.batch` 依赖，也没有多 picking 会话；`get_pickings(picking_ids)` 只用于列表过滤，不是同时操作多单。
- **验证**：`validate_picking` 最终调用 `picking.action_validate_from_scanner()` → 原生 `button_validate`；是否弹欠单由原生 `create_backorder`（ask/always/never）控制，不强制“全部完成”。
- **配置**：按作业类型配置扫描源位/目标位、批次扫描、包装、验证前检查等（`qz_require_*`），并有 `qz.scanner.session` / 日志模型做审计。

对应到本方案：

| 问题 | qz_scanner 的做法 | 对本模块的建议 |
|---|---|---|
| B1 | 无批次，只有单单据 + 新建空单扫码 | 若“批量调拨”指多单一起拣，A 仍需新建；若指“快速新建并连续扫多产品”，直接复用 qz 的空单模式，不必做批次 |
| B2 | 单模块，无桥接 | qz 不涉及批次，不能作为反对桥接的依据；批次仍建议独立桥接 |
| B3 | 天然单单据，不跨单分配 | 与建议一致：批次内按当前单扫码 |
| B5 | 跟随原生 `create_backorder`，允许部分完成 | 需重新确认：批次验证建议“全部完成”，否则多单欠单弹窗会非常混乱 |
| B8 | 空 picking + 扫码追加行，无多行录入向导 | 推荐照此实现“新建调拨”，不做独立批量创建向导 |

据此新增一个可选入口：

- **新建调拨（空单 + 扫码）**：作业类型列表页右上「+」→ 创建空 picking → 直接进扫码页，扫产品即追加明细。适用于“临时补一张调拨单”的场景，和批次（多单一起拣）不是同一功能。

### 9.9 已完成：空单扫码模式（2026-11-20）

- 工作台作业类型列表页新增黄色「+」按钮（仅类型入口显示）。
- 新增服务方法 `create_empty_picking(warehouse_id, picking_type_id)`：
  - 校验作业类型属于当前仓库；
  - 用作业类型默认源/目标库位创建 draft picking；
  - 创建 `wiz.stock.barcodes.picking` 并设 `allow_new_products=True`；
  - 写入最近访问，返回扫码动作。
- 扫码向导新增 `allow_new_products`：
  - 未追踪产品：跳过 `barcode_new_product_policy`，直接 `action_force_add`（新建 move + 拣 1 件）。
  - 追踪产品：扫产品后进入批次/序列号步骤，扫码后由 `_scan_new_product_lot` 新建 move 并标记 picked。
  - 首件创建 move 后自动确认 picking；`_create_picking_move` 在空单模式下 `_do_unreserve()`，避免“预留行 + 已拣行”重复。
- 后端验证（shell，已回滚/清理测试数据）：
  - 空 `WH/OUT` + 扫 `TEST-EMPTY-001` → 1 条 move（需求 1）+ 1 条 picked 行。
  - 空 `WH/OUT` + 扫序列号产品 → picking 进入 `assigned`，仅 1 条 picked 行，无重复预留行。
  - 测试用条码已从产品上移除。
- 浏览器验证：类型页「+」按钮可见；端到端点击因自动化浏览器崩溃未能完成（环境问题，非代码报错）。

### 9.10 批次桥接模块（2026-11-20 已实现）

`stock_barcodes_picking_batch`（依赖 `stock_barcodes_picking` + `stock_picking_batch`）按 Pixso 新设计稿（`62:5795` / `62:2793` / `62:10757` / `62:12389`）重构：

**列表 / 新建流程**

- 列表：4 张状态卡使用原生批次状态（所有 / 草稿 / 进行中 / 已完成），卡片底色与批次状态徽标同色（深色 / 浅灰 / 荧光黄 / 绿）；批次行显示「n 明细行」、🚚 仓库:作业类型、往来、日期时间+操作人。
- 新建拆成两页：
  1. `作业类型选择`：作业类型卡（OUT/PC/IN/SFP/INT）+ 候选数，**无「全部」**，点击即进入下一步；
  2. `单据选择`：按所选类型列出未入批单据（星标/单号/往来/日期/状态徽标）、分页、黄色「确认」；确认后**直接进入批量扫码页**。
- 服务方法：`get_batch_create_types`、`get_batch_candidates(warehouse, picking_type)`、`create_batch(warehouse, picking_type, picking_ids)`（类型必填并校验一致）。
- 加单：复用 `单据选择` 页（`params={batch_id, mode:"add"}`），类型固定为批次类型，按钮「加入批次」。

**批量扫码页（复用主扫码页）**

- 桥接模块 `_inherit` `wiz.stock.barcodes.picking` 增加 `batch_id`；主扫码页通过 `patch(PickingScanApp)` + OWL 静态模板继承扩展，主模块不装桥接时行为不变。
- `get_scan_state`：汇总批次内所有单据的 `move_ids` 与 `rows`，每张卡片带 🚚 单据号；`total_done/total_demand` 为批次合计；页头单据名显示批次号；齿轮菜单改用批次表单 toolbar（含「打印报告：批量调拨」）；扫描提示里的单据名替换为批次号。
- **扫码自动定位**：扫产品 → 第一张仍有该产品剩余需求的单据；扫批次/序列号 → 第一张有该批次未拣行的单据；扫包裹 → 包裹所在单据；库位条码与多步流程（产品→批次→数量）期间不切换。点击/操作任意卡片（改数、+1、批次行编辑、拆包、取消拣货、取消包裹、装包等）时，后端按 `move_id/line_id/package_id` 自动切到该卡片所属单据。
- 进度 = 批次合计；`canValidate` 在批次仍活跃时可用。
- **批次验证**：逐单检查装包强制规则；逐单逐 move 校验已拣 ≥ 需求（只算 `picked` 行），未满显示红条并列出未完成单号；全部满足后 `batch.action_done()`，成功后自动返回批次列表。
- **加单**在底部「更多…」；**打印**在右上角齿轮（原生 CogMenu）。
- 暗色/亮色两套：扫码页沿用 `--scan-*`（`web.assets_web_dark` 已有暗色值），批量页新增 `batch_workbench.dark.scss`。
- **统一抬头（Pixso 页面 4）**：批量列表/新建页补 `BY ODOO` 品牌条；新建页标题固定「新建批量调拨」+ 面包屑副标题；「+」移到扫码行最右；补黄色仓库条（列表可切换仓库，进入新建后锁定不可改）；相机图标移入条码输入框（主工作台、扫码页同步调整，不再单独占一个方块按钮）。
- **页面宽度对齐**：扫码页（与工作台一致）在平板横屏/PC 下限制为 1000px 内容列并居中；顶部各区块/提示条/产品列表对齐同一列，底部深色栏保持通栏、内容与页面列对齐。窄屏（<1000px）仍铺满。宽度规则放在样式块末尾，避免被组件的 `margin`/`padding` 简写覆盖（提示条需 `width:100%` 否则会收缩）。
- **相机图标**：由硬编码黑色 SVG `<img>` 改为共用内联模板 `stock_barcodes_picking.CameraIcon`（`fill="currentColor"`），跟随 `--scan-ink` / `--wb-ink`：暗色 `#E6EDF7`、亮色 `#111`；主工作台、库存盘点、批量列表/新建、扫码页统一使用，并已移入条码输入框。

**已验证**

- shell：类型必选/跨类型拒绝；`create_batch` 返回扫码动作；汇总 `move_ids`/`rows` 带单据号；扫产品自动切到目标单据；`set_active_move` 跨单切换；缺量验证返回 False 并列出单号；全拣后验证 True 且批次 `done`。
- 浏览器（设计稿对照）：
  - 列表 4 张状态卡 + 「+」；作业类型页 5 张卡、无「全部」；单据选择页勾选 2 单 → 确认 → 直接进入新批次扫码页。
  - 扫码页 3 张卡片来自两张单据，卡片显示 🚚 WH/OUT/00043/00044 等单据号；扫 `04620065570483` 自动定位并高亮目标单据卡片，进入批次步骤。
  - 齿轮含「打印报告：批量调拨」；「更多…」含「加单」；验证按钮列出两张未完成单号。
  - 「加单」选 1 单后返回扫码页，产品 3 → 4 ITEMS，进度 1/100 → 1/108。
- 测试批次已清理（含原有 `BATCH/IN/00006`，其单据已释放未删除）。

**遗留**

1. 批次全拣完成后在 UI 走一遍「验证 → 自动回列表 → 批次 done」（验证逻辑已由 shell 覆盖）。
2. 大批次（>20 单）时汇总页性能需实测，必要时做分页/懒加载。
3. 卸载残留回归（本次重构未新增表/列，沿用 §8.6.4 流程复核）。
