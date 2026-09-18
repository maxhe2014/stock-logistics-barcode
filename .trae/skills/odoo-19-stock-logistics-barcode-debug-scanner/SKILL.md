---
name: odoo-19-stock-logistics-barcode-debug-scanner
description: 当用户需要排查 OCA stock-logistics-barcode 仓库（Odoo 19.0）的扫码功能异常时使用此技能。覆盖：扫码无反应、扫码后字段未填、扫码报 not found、引导模式不显示 todo、lot 自动创建失败、bus 推送不刷新、负库存报错、多候选 picking 选择异常、前端 OWL 控制器不响应等问题。触发词包括：扫码不响应、扫码没反应、扫码字段没填、barcode not found、扫码报错、引导模式、guided mode、todo 不显示、lot 创建失败、create_lot、auto_lot、bus_bus 不推送、longpolling、扫码界面、OWL form_controller、kanban_renderer、negative quant、候选 picking、candidate_picking、option_group 配置、扫码音效、扫码枪调试。
---

# odoo-19-stock-logistics-barcode-debug-scanner

## 描述
针对 OCA `stock-logistics-barcode`（Odoo 19.0）的扫码功能提供结构化排错指南。本技能只读、不修改源码；给出排查路径与可能的修复方向，最终修改由实现任务完成。

## 使用场景
- 当用户报告"扫码枪扫了没反应"时
- 当用户报告"扫了 location 但字段没填"时
- 当用户报告"扫码界面报 Barcode not found"时
- 当用户报告"引导模式不显示 todo 列表"时
- 当用户报告"扫码后界面不自动刷新"时
- 当用户报告"扫 lot 报错"或"lot 自动创建失败"时
- 当用户报告"前端 OWL 报错"或"kanban 渲染异常"时
- 当用户要新增扫码步骤或修改 option_group 配置时

## 指令

### 1. 扫码事件链路（先理解再排错）
```
扫码枪(HID键盘) → barcodes.barcode_events_mixin 监听键盘
  → 触发 barcode_scanned 事件
  → wiz.stock.barcodes.read._on_barcode_scanned()
  → 按 option_group 的 step 顺序匹配 location/product/lot/packaging/package
  → 写入 wizard 字段
  → 调用 stock_move_line/stock_move 写入业务数据
  → barcode_events_mixin.send_bus_done() 推 bus.bus
  → 前端 StockBarcodesFormController 监听 stock_barcodes_form_update channel
  → 重新渲染
```

链路任一环断都会导致现象，按现象定位环节。

### 2. 按现象定位

#### 现象 A：扫码枪扫了完全没反应
**优先级**：前端资源未加载
1. 浏览器 F12 控制台是否有 JS 报错？
2. Network 是否加载了 `stock_barcodes/static/src/**/*.esm.js`？
3. 资产缓存是否过期？访问 `http://127.0.0.1:8071/web/assets/debug` 重新编译。
4. 隐身窗口 + `Ctrl+Shift+R` 强刷。
5. 检查 `__manifest__.py` 的 `assets` 段，`web.assets_backend` 是否包含 `stock_barcodes/static/src/**/*.esm.js`。
6. 确认 `barcodes` 核心模块已装且 `barcodes.barcode_events_mixin` 已注入到当前模型。

#### 现象 B：扫码有反应但字段没填
**优先级**：option_group 配置
1. 当前 `stock.picking.type.barcode_option_group_id` 是否绑定正确？
2. 打开 `Settings → Technical → Barcode Options`，找到对应 `option_group`：
   - `option_ids` 中 `step` 顺序是否合理（location=1, product=2, lot=2）
   - `to_scan=True` 是否开启
   - `required=True` 是否合理
   - `field_name` 是否拼写正确（参考 `stock_barcodes_action.py` 的 `FIELDS_NAME`）
3. 检查 wizard 当前 `step` 值，扫码只匹配当前 step 的字段。
4. 检查 `manual_entry` 是否被误开（手动模式不自动填值）。

#### 现象 C：扫码报 "Barcode not found"
**优先级**：数据未匹配
1. 检查扫码内容是否在 `product.product.barcode`、`product.packaging.barcode`、`stock.location.barcode`、`stock.lot.name`、`product.barcode.multi.name` 中。
2. 若 lot 不存在且 `option_group.create_lot=False` → 在 option_group 勾选 `create_lot`。
3. 若包装扫码匹配多条产品 → 检查 `product.packaging` 是否有重复 barcode。
4. 日志看 `_logger.warning` 与 `message_type=not_found`，确认匹配逻辑走的哪条分支。

#### 现象 D：引导模式不显示 todo
**优先级**：todo 配置
1. `option_group.barcode_guided_mode = "guided"` 是否开启？
2. `option_group.show_pending_moves = True`？
3. `option_group.source_pending_moves`：详细操作用 `move_line_ids`，操作列表用 `move_ids`。
4. `option_group.group_key_for_todo_records` 是否语法正确（`object.location_id,object.product_id`）？
5. wizard 调用 `fill_pending_moves()` 与 `determine_todo_action()` 是否成功（看日志）。
6. picking 是否有 `assigned` 状态的 move_line；未预留时需 `confirmed_moves=True`。

#### 现象 E：扫码后界面不刷新
**优先级**：bus 推送链路
1. `bus.bus` 表是否有 `stock_barcodes_form_update` channel 的记录？
2. longpolling 是否启动？检查 `server_wide_modules` 与 `/longpolling/poll` 端点。
3. 前端 `form_controller.esm.js` 的 `busService.addEventListener("notification", handleNotification)` 是否注册成功？
4. 多 worker 时确认 `gevent` 或 `longpolling` worker 正常。
5. `barcode_events_mixin.send_bus_done` 是否被调用（看 wizard 是否抛异常中断）。

#### 现象 F：lot 自动创建失败
**优先级**：create_lot 与权限
1. `option_group.create_lot=True`？
2. 当前用户是否有 `stock.group_production_lot` 权限？
3. `product_tracking` 是否为 `lot` 或 `serial`？`none` 类型不能建 lot。
4. `wiz.stock.barcodes.new.lot` wizard 是否能正常打开（看 `stock_production_lot_views.xml`）。
5. lot 名是否冲突（同名 lot 已存在且 `create_lot` 不会复用）。

#### 现象 G：负库存报错
**优先级**：option_group 配置
1. `option_group.allow_negative_quant=True` 是否开启？
2. 检查 `stock.quant` 在目标 location 是否真为负；Odoo 默认禁负库存。
3. 若仍报错，看 `stock_move._action_assign()` 的逻辑，可能需要 `confirmed_moves=True` 绕过预留。

#### 现象 H：多候选 picking 选择异常
**优先级**：candidate_picking wizard
1. `wiz.candidate.picking` 是否正确生成候选列表？
2. `option_group` 的 `source_pending_moves` 配置是否合理？
3. picking 状态是否 `assigned`；未分配的 picking 不会进入候选。
4. 检查 `wiz_stock_barcodes_read_picking.py` 的 `_field_candidate_ids` 与 `picking_mode`。

#### 现象 I：前端 OWL 报错
**优先级**：JS 模块导入
1. F12 控制台具体报错信息？
2. `form/form_controller.esm.js`：是否 `super.setup()` 调用？
3. `kanban/kanban_renderer.esm.js`：是否正确继承 `KanbanRenderer`？
4. ESM 导入路径是否正确（`@odoo/owl`、`@web/views/form/form_controller`）？
5. `__manifest__.py` 的 `assets` 段是否包含 `views/form/*.esm.js` 与 `views/kanban/*.esm.js`？
6. `numeric_step.xml` 是否通过 `after` 注入到 `web_widget_numeric_step` 之后（顺序错会导致覆盖失效）。

### 3. 日志与调试技巧
- 临时加日志：在 `wiz.stock.barcodes.read._on_barcode_scanned` 入口与每个 `action_barcode_scanned` 加 `_logger.info`。
- 数据库直查：
  ```sql
  SELECT id, name, barcode FROM product_product WHERE barcode IS NOT NULL;
  SELECT id, name, barcode FROM stock_location WHERE barcode IS NOT NULL;
  SELECT id, name, product_id FROM stock_lot WHERE name = '<scanned>';
  SELECT * FROM product_barcode_multi WHERE name = '<scanned>';
  SELECT * FROM bus_bus WHERE channel LIKE '%stock_barcodes%' ORDER BY id DESC LIMIT 10;
  ```
- 浏览器调试：在 `form_controller.esm.js` 的 `handleNotification` 加 `console.log`。
- 启用 Odoo debug 模式：URL 加 `?debug=1`，看字段 ID 与视图结构。

### 4. 扫码枪硬件自检
- 用记事本测试扫码枪能否输出条码内容（确认 HID 模式正常）。
- 检查扫码枪是否在末尾发送回车（Enter）；Odoo 监听回车触发。
- 长条码（GS1）需扫码枪支持"多段拼接"，确认扫码枪配置。
- 蓝牙扫码枪偶发断连，重启扫码枪或重新配对。

### 5. 关键文件索引
- 扫码事件入口：[barcode_events_mixin.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/models/barcode_events_mixin.py)
- Wizard 基类：[stock_barcodes_read.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read.py)
- Picking wizard：[stock_barcodes_read_picking.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read_picking.py)
- Inventory wizard：[stock_barcodes_read_inventory.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read_inventory.py)
- 选项配置：[stock_barcodes_option.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/models/stock_barcodes_option.py)
- 动作配置：[stock_barcodes_action.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/models/stock_barcodes_action.py)
- Lot 即时建：[stock_production_lot.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_production_lot.py)
- 前端 FormController：[form_controller.esm.js](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/static/src/views/form/form_controller.esm.js)
- 前端 KanbanRenderer：[kanban_renderer.esm.js](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/static/src/views/kanban/kanban_renderer.esm.js)
- 测试夹具基类：[common.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/tests/common.py)

### 6. 不要做的事
- 不要直接 `ALTER TABLE` 改 wizard 字段（wizard 是 TransientModel）
- 不要在 `option_group` 之外硬编码扫码逻辑（破坏配置化设计）
- 不要在前端用 jQuery 直接操作 DOM（用 OWL 状态驱动）
- 不要在 `bus.bus` 推送时传不可序列化对象（payload 必须 JSON-safe）
- 不要在 `pre_init_hook` 里调用 ORM（只能 raw SQL）

## 示例

**用户报告**："扫了 product 的条码，但 wizard 里 product_id 还是空的"

**排查路径**：
1. 确认 wizard 当前 `step`（应该是 2，product 所在步骤）
2. 确认 `option_group.option_ids` 中 `field_name=product_id` 的 `to_scan=True`、`required=True`
3. 确认 product 的 `barcode` 字段确实有值：`SELECT barcode FROM product_product WHERE id=<pid>`
4. 若 product 有 `tracking='lot'`，且 lot 未扫，可能匹配被 lot 步骤拦截
5. 看 `stock_barcodes_read.py` 的 `_on_barcode_scanned` 中 product 匹配分支日志
6. 检查 `manual_entry` 是否被误开

**用户报告**："引导模式 todo 列表是空的"

**排查路径**：
1. picking 状态必须 `assigned`（有 `move_line_ids`）
2. `option_group.source_pending_moves = "move_line_ids"`（详细操作）
3. `option_group.show_pending_moves = True`
4. `option_group.barcode_guided_mode = "guided"`
5. wizard 调用 `fill_pending_moves()` 是否抛异常
6. picking 的 `move_line_ids.qty_done` 是否已达 `reserved_uom_qty`（全部 done 的不进 todo）
