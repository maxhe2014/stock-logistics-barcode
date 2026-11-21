# AGENT 指南 — stock-logistics-barcode（Odoo 19 扫码工作台）

本文件给后续 AI/开发者提供项目速览、运行方式、设计约定与踩坑记录。改动前先读本文件和
`stock_barcodes_picking/TO-DO LIST.md`（主设计/决策日志）。

## 1. 项目是什么

Odoo 19 仓库扫码应用，位于 OCA `stock-logistics-barcode` 的 fork 仓库，当前分支 `19.0`。

| 模块 | 作用 |
|---|---|
| `stock_barcodes_picking` | **主模块**：拣货扫码页（client action）+ 扫码工作台（首页/状态列表/作业类型列表/库存盘点） |
| `stock_barcodes_picking_batch` | 批量调拨桥接：批次列表/新建/汇总扫码/批次验证（复用主模块扫码页） |
| `stock_barcodes_mrp` | 制造扫码应用，**复用部分 `o_scan_*` 类名**，改样式时必须限定作用域 |
| `stock_barcodes` | OCA 基础扫码模块（不改） |
| `web_ir_actions_client_scan` | 扫码 action 桥接（不改） |

关键页面：
- 扫码页：`action_picking_barcode_scan`（action 690），tag `stock_barcodes_picking.PickingScanApp`
- 工作台：tag `stock_barcodes_picking.ScanWorkbench`
- 批量工作台：tag `stock_barcodes_picking_batch.BatchWorkbench`

## 2. 运行环境

- 根目录：`/run/media/max/DATA1/projects/odoo-dev/19.0`
- 配置：`config/odoo.conf`（数据库 `odoo19`，HTTP `8071`，gevent `8072`，8 workers）
- 解释器：`19.0/venv/bin/python`
- 启动/重启：`bash 19.0/start_odoo.sh`（会 `pkill` 旧进程并等待约 60 秒）
- 日志：`/tmp/odoo.log`

改动的生效方式：
- **Python**（模型/向导/服务）→ 必须重启 Odoo。
- **XML 模板 / JS / SCSS** → 属于静态资源，需要让 Odoo 重建资源包（见 §6），浏览器再强制刷新。

## 3. 代码地图

```
stock_barcodes_picking/
├── static/src/
│   ├── picking_scan_app.{js,xml,scss,dark.scss}      # 扫码页
│   ├── shared/scan_ui.scss, scan_ui.dark.scss         # 全局调色板 + 共用控件
│   └── workbench/
│       ├── scan_workbench.{js,xml,scss,dark.scss}    # 工作台/列表/盘点
│       └── open_apps_menu.js                         # 九宫格回功能选择页
├── models/stock_barcodes_workbench.py                # 服务模型（所有 RPC）
├── wizard/stock_barcodes_picking.py                  # 扫码状态机（scan_mode/步骤）
└── TO-DO LIST.md / DEVELOPMENT.md / PACKAGE_SCAN_MODES.v4.md
```

`static/src/shared/scan_ui.scss` 是**唯一调色板来源**：定义 `--ui-*`，扫码页用
`--scan-*`、工作台/批量页用 `--wb-*` 别名引用；品牌条、方形硬边按钮、条码输入框三组
组件也只写一次。改颜色/控件样式优先改这里，不要在页面文件里复制。

> Odoo 19 **禁止 SCSS 本地 `@import`**。共享文件必须单独登记在 `__manifest__.py` 的
> `web.assets_web` / `web.assets_web_dark` 中，不能靠 `@import` 引入。

## 4. 设计规范（Pixso「野兽」主题）

- 内容列：抬头、提示条、产品卡/作业卡统一左右 16px，平板/PC 最大 1000px 居中。
- 硬边风格：2px 描边 + `4px 4px 0` 硬阴影；按下整块位移 4px 并去阴影。
- 颜色：`page #F7F3E8 / card #FFF / ink #111 / border #111 / yellow #FFE500 / pink #FF4D97 /
  green #00D97E / orange #FF6B2C / blue #4361EE / red #DB3847`（暗色见 `scan_ui.dark.scss`）。
- 投影规则：卡片类用 `--ui-shadow`（暗色为亮色），控件/按钮用 `--ui-shadow-deep`
  （暗色不可见）；强调面（黄/粉/蓝等）描边统一用 `--ui-border`，暗色下自动变亮。
- 页脚按键：卡片底 + 强调描边（默认黄色）；「装包」蓝色描边（`.o_scan_key_blue`）；
  「验证」黄底（`.o_scan_key_primary`）。
- 作业类型卡：彩色代号条（ALL/OUT/PC/IN/SFP/INT/IA）+ 中文名 + 右下粉色数量徽标。
- 仓库入口：首页/状态列表/作业类型列表/库存盘点都用整条黄色仓库栏
  （名称 + ▾ + `张明 · 09:42`），不再使用右上短按钮。
- 深色只通过 `web.assets_web_dark` 覆盖 `--ui-*`，**不要再加 `[data-theme]` 分支**。
- 图标：相机用共享模板 `stock_barcodes_picking.CameraIcon`（`currentColor`）；
  黑色 SVG 在暗色下用 `filter: invert(1)`。

## 5. 关键行为与硬约束

- **扫码页返回**：`onBack()` 走 `browser.history.back()`，与浏览器后退一致；
  `wiz_id` 存 `sessionStorage`（30 分钟）用于后退恢复；`pageshow(persisted)` 时重载防卡死。
- **九宫格回功能选择页**：`sessionStorage["scan_open_apps_menu"]=1` + `open_apps_menu.js`
  点击 Web Responsive 应用网格按钮；**不要**写 `is_redirect_home=True`（会盖住表单/扫码页）。
- **批量页返回**：`doAction(..., {stackPosition: "replaceCurrentAction"})`，避免 URL 堆栈叠加。
- **`doAction` 之后禁止再碰 state / ORM / notification**：组件已被销毁，Odoo 会抛
  `Component is destroyed`（曾导致「加载单据列表失败」误报）。
- **新建调拨（+）**：`create_empty_picking()` 建空 draft 单 + `allow_new_products=True`，
  扫产品才追加明细并自动确认；收据类型默认进入 `pack` 扫描模式是设计行为。
- **一页一维度**：状态页只能再筛作业类型，类型页只能再筛状态；切仓库不重置筛选。
- **作用域**：新样式必须限定在 `.o_picking_scan_app` 或 `.o_scan_workbench` 内，
  避免影响 `stock_barcodes_mrp` 的同名 `o_scan_*` 类。
- 文案用 `this.tr(...)`，不要直接写死中文到 JS 逻辑里；模板里的中文按现有风格即可。

## 6. 修改后的验证流程

1. **SCSS 编译**：
   ```bash
   cd 19.0
   venv/bin/python - <<'PY'
   import sass
   for f in ["shared/scan_ui.scss","picking_scan_app.scss","picking_scan_app.dark.scss",
             "workbench/scan_workbench.scss","workbench/scan_workbench.dark.scss"]:
       print(f, len(sass.compile(filename="addons/stock-logistics-barcode/stock_barcodes_picking/static/src/"+f)))
   PY
   ```
2. **Python / XML**：`venv/bin/python -m py_compile <file>`、`ElementTree.parse(<xml>)`。
3. **后端逻辑**：用 Odoo shell（不影响运行中的服务）：
   ```bash
   cd 19.0
   printf '%s\n' "print(env['stock.barcodes.workbench'].get_workbench_list(False,'status','ready','all',1,5))" \
     | venv/bin/python src/odoo/odoo-bin shell -c config/odoo.conf -d odoo19 --no-http --log-level=error
   ```
4. **资源包重建**（Odoo 会缓存旧的 min.css/min.js，必须删附件后重新请求）：
   ```bash
   # 库账号见 config/odoo.conf（db_user / db_password）
   psql -h localhost -U max -d odoo19 -c "delete from ir_attachment
     where url like '%/web/assets/%' and (url like '%web.assets_web.min.css%'
     or url like '%web.assets_web_dark.min.css%' or url like '%web.assets_web.min.js%');"
   ```
   然后在浏览器里强制刷新（Ctrl+F5 / 手机下拉刷新）。
5. **视觉验证**：无头 Chromium 可用（snap 版**读不到 `/tmp`**，harness 放 `$HOME`）：
   ```bash
   chromium --headless --disable-gpu --no-sandbox --hide-scrollbars \
     --window-size=390,844 --screenshot=$HOME/preview.png file://$HOME/preview.html
   ```
   用 PIL 采样像素可核对边距/颜色；不要只凭截图“看起来对”。

## 7. 已知踩坑

- **旧 CSS/JS 不生效**：先清资源包附件再强刷，否则会看到上一次构建的样式。
- **SCSS 本地 `@import` 报错**：`Local import ... is forbidden for security reasons`，改为登记 asset。
- **Sass 把 CSS `max()` 当函数**：用 `#{'max(...)'}` 插值输出。
- **XML 注释含 `--`** 会解析失败。
- **提示条/页面宽度被覆盖**：`margin`/`padding` 简写与宽度规则同权重时后写者胜，宽度规则放样式块末尾或提高选择器权重。
- **`Component is destroyed`**：导航后仍有在途 ORM/刷新，去掉调用或在错误处理中忽略。
- **测试数据**：只删除明确标记的测试单据/批次，不要批量清理用户单据；改共享产品条码后要还原。

## 8. 协作约定

- 分支 `19.0`，提交信息用中文 + Conventional 前缀（如
  `feat(stock_barcodes_picking): ...`）。未经用户明确要求不要提交/推送。
- 设计/决策变更同步写入 `stock_barcodes_picking/TO-DO LIST.md`（§8/§9 章节）。
- 不要为了“顺手”重构无关模块；改动保持最小、可验证。
