# stock_barcodes_picking 开发文档（WIKI）

> 模块版本：`19.0.2.0.0`（扫码页 v4.4 最终实现）
> 最近整理：2026-11-17
> 适用对象：后续接手本模块的开发 / 设计还原 / 排障
> 配套文档：`PACKAGE_SCAN_MODES.v4.md`（扫码页 v4.4 最终口径）、`RULES.md`（业务规则逐条审计）、`TO-DO LIST.md`（功能待办）、`TO-DO LIST - UI重构.md`（界面重构待办）

本文只讲**架构怎么搭、UI 怎么还原、开发怎么跑、坑在哪**。业务规则（扫码分发顺序、数量写入、超量策略等）以 `RULES.md` 为唯一口径，不在此重复。

---

## 1. 模块速览

| 项 | 值 |
|---|---|
| 技术名 | `stock_barcodes_picking` |
| 依赖 | `barcodes`、`stock`、`web`（不依赖 OCA `stock_barcodes`，该模块 Odoo 19 兼容性差） |
| 客户端 action | `stock_barcodes_picking.action_picking_barcode_scan` |
| 前端框架 | OWL 2（`PickingScanApp` Component） |
| 后端载体 | TransientModel `wiz.stock.barcodes.picking` |
| 入口 | 调拨单表单「条码扫描」按钮、列表/看板顶部 Scan、列表行/看板卡片 Scan |

三种入口的状态准入条件不同，见 `RULES.md` 的 ENT-001～ENT-003。

---

## 2. 架构分层

```
┌─────────────────────────────────────────────────────────────┐
│ 视图层  static/src/picking_scan_app.xml   (OWL 模板)          │
│         static/src/picking_scan_app.scss  (设计稿还原样式)     │
│         static/src/picking_scan_app.dark.scss (深色 token)     │
│         static/src/picking_scan_app.css   (跨组件/控制面板规则) │
├─────────────────────────────────────────────────────────────┤
│ 交互层  static/src/picking_scan_app.js    (Component 1610 行)  │
│         只做：事件 → 单次 RPC → 合并 state → 重渲染            │
├─────────────────────────────────────────────────────────────┤
│ 业务层  wizard/stock_barcodes_picking.py                      │
│         process_barcode_and_dispatch(barcode) → {action,state} │
│         get_scan_state() → 快照                                │
├─────────────────────────────────────────────────────────────┤
│ 配置层  models/stock_picking_type.py（作业类型上的扫码开关）    │
│         models/stock_picking.py（入口按钮显隐与 action 构造）   │
└─────────────────────────────────────────────────────────────┘
```

**铁律：前端不写业务判断。** 扫描规则、数量写入、超量策略、批次分配全部在后端 wizard；前端只负责把一次扫码的结果渲染出来。唯一例外是纯 UI 态（选中行 `active_move_id` 的高亮、序列号卡折叠、本次命中高亮）。

---

## 3. 关键文件地图

| 文件 | 职责 | 什么时候改 |
|---|---|---|
| `wizard/stock_barcodes_picking.py` | 全部扫码业务逻辑 + `get_scan_state` 快照 | 改扫码规则、数量、批次、包装 |
| `wizard/stock_barcodes_picking_views.xml` | 后端表单视图（主要给非 OWL 场景兜底） | 加后端字段 |
| `models/stock_picking.py` | `action_barcode_scan()` 入口、状态准入 | 加入口或改准入 |
| `models/stock_picking_type.py` | Barcode 配置页字段 | 加配置项 |
| `static/src/picking_scan_app.js` | OWL 组件、事件处理、state | 改交互 |
| `static/src/picking_scan_app.xml` | 全部界面结构 | 改界面结构 |
| `static/src/picking_scan_app.scss` | 亮色设计 token + 全部组件样式 | 改配色/尺寸 |
| `static/src/picking_scan_app.dark.scss` | 深色 token 覆盖（仅 `web.assets_web_dark` 加载） | 改深色 |
| `static/src/picking_scan_app.css` | 控制面板按钮排序、滚动容器等**跨组件**规则 | 改动 Odoo 原生控件 |
| `static/src/img/*.svg` | 顶栏/扫码行图标（**直接从设计稿搬**，不手绘） | 换图标 |
| `tests/test_stock_barcodes_picking.py` | 后端回归测试 | 改业务逻辑必须同步 |

---

## 4. 数据流

```
扫码枪 / 手输 / 相机
      │
      ▼
_onScan(barcode)          ← 入队 this._scanQueue，防并发乱序
      │
      ▼
_scanOne(barcode)
      │  记录扫码前各 pickedLots 数量（用于反查命中行）
      ▼
orm.call('wiz.stock.barcodes.picking', 'process_barcode_and_dispatch', [[wizId], barcode])
      │  返回 { action?, state }
      ├─ 有 action → doAction()（切单 / 验证弹窗 / 选择候选）
      ▼
Object.assign(this.state, res.state)   ← 后端快照整体覆盖
      │
      ├─ _enrichMoves()：补前端派生的展示字段
      ├─ 命中行反查：picked_quantity 增加的 lot → recentScanLotKey
      ▼
渲染（XML 模板 + state）
```

**要点**

- `state` 是「后端快照 + 少量纯 UI 字段」的混合体，合并一律用 `Object.assign`，不要逐字段赋值。
- 命中行反查依赖「扫码前的数量基线」，新增数量字段时必须同步这份基线，否则高亮错行。
- `message_type` → CSS 类由 `alertClass` getter 统一映射（`info/success/warning/error/not_found/more_match`）。

---

## 5. UI 结构

```
.o_picking_scan_app  (flex column, 全高, overflow: hidden)
├── .o_scan_topbar            源单据 | 单号 + 进度 | 刷新键
├── .o_scan_scanrow           返回 | 输入框(条码图标 + input + 相机) | 齿轮(CogMenu)
├── .o_scan_hintbar           提示条（三行：模式提示 / 操作提示 / 当前操作）
├── .o_scan_pull_indicator    下拉刷新提示（下拉刷新 / 松开刷新 / 刷新中）
├── .o_picking_scan_rows      产品行列表（滚动容器）
│   └── .o_scan_row           产品行（数量追溯按包裹拆行）
│       ├── .o_scan_row_top       从 / 至 / 需求
│       ├── .o_scan_row_main      产品名 + 已拣 + +1 / 修改
│       ├── .o_scan_qty_pkg       数量追溯行的包裹号
│       └── .o_scan_lots          批次下拉（头 + 展开面板，逐项分隔线）
├── .o_scan_footer            进度 + 更多… / 模式按钮 / 验证
└── .o_scan_split_dialog      行编辑 / 移除包裹 / 取消拣货·拆包选包
```

### 5.1 设计 token（当前生效值）

| Token | 亮色 | 深色 |
|---|---|---|
| `--scan-page` | `#F2E9E2` | `#161D20` |
| `--scan-card` | `#FDF7F4` | `#48525C` |
| `--scan-frame` | `#DED5CE` | `#3B4543` |
| `--scan-text` / `--scan-text-2` | `#000000` / `#74787B` | `#FFFFFF` / `#A4A5A6` |
| `--scan-row-bg` / `--scan-fold-bg` | `rgba(37,77,195,.12)` / `.22` | `rgba(37,77,195,.25)` / `.4` |
| `--scan-hint-bg` / `-fg` | `#D2D9EC` / `#254DC3` | 同左（深色也用浅紫底） |
| `--scan-ok-bg` / `-fg` | `#66E7B0` / `#000000` | 同左 |
| `--scan-danger-bg` / `-fg` | `#F0315B` / `#FFFFFF` | 同左 |
| `--scan-key-bg` / `-fg` | `#F2E9E2` / `#000000` | `#161D20` / `#FFFFFF` |
| `--scan-key-shadow` / `-light` | `#DED5CE` / `#FDF7F4` | `#0B0F11` / `#2A3339` |
| `--scan-lot-bg` | `#FDF7F4` | `#404144` |
| `--scan-green` / `--scan-purple` | `#254DC3` / `#8174AA` | `#4C7BD9` / `#8E82B5` |
| `--scan-hl` | `rgba(37,77,195,.28)` | `rgba(76,123,217,.5)` |

> 旧 token `--scan-primary` 已不存在；深色实际以 `picking_scan_app.dark.scss` 为准，主 SCSS 的 `[data-theme="dark"]` 仅作兜底。

### 5.2 尺寸

| 元素 | 规格 |
|---|---|
| 顶栏 | 高 34px，`padding: 0 10px`，`space-between` |
| 顶栏 / 扫码行按钮 | 30×30，圆角 4px；新拟态外凸 `2/2/4/4`，按下 inset `2/2/2/2` |
| 扫码输入框 | 高 30px，圆角 8px，白底无边框，内嵌相机 |
| 提示条 | 最小高 28px，圆角 6px，`padding: 6px 10px`，三行 `gap: 2px`；高度随内容自适应 |
| 产品框 | 圆角 8px，`padding: 10px`，内凹阴影（区分上下行） |
| 批次/序列号项 | 最小高 26px，底部 1px 分隔线（`--scan-frame`） |

### 5.3 行为约定（容易改错的地方）

1. **序列号卡片默认折叠**：`expandedSerialRows` 为空即全部收起（语义是"展开集合"，不是"折叠集合"）。
2. **命中高亮常驻**：扫到序列号后该行绿色高亮一直保留，**不自动消失**；任何下一次扫码（无论是否命中）先清空再按结果重新点亮。
3. **折叠态命中**：摘要行显示刚扫的序列号并高亮，**不自动展开**；展开态命中只闪（亮）那一行，也不自动收起。
4. **深色锁定**：页面锁 `color-scheme: light`，深色靠 `[data-theme="dark"]` + `web.assets_web_dark` 两套 token，**两处必须同步改**。
5. **数量追溯行按包裹拆行**：`_get_scan_rows_v4()` 会把同一 move 拆成「未装包剩余行 + 每个包裹一行」；行需求按装箱顺序分配且总和恒等于原单需求（见 `PACKAGE_SCAN_MODES.v4.md` §0.2）。
6. **数量追溯扫产品 = +1**：只加到未装包剩余行，不再进入「输入数量」步骤。
7. **取消拣货 / 扫描拆包**：取消拣货对数量追溯与批次号产品一次只处理 1 件（多包裹时由 `unclaim_choices` 弹窗选包）；扫描拆包的单件处理仅数量追溯产品；选择前不写数据。
8. **超拣 `warn`**：行 +1/扫码 +1 被拦下时写入 `pending_add` 并置 `visible_force_done`，底栏「强制」按钮经 `action_force_done()` 按原目标数量强制写入；`forbid` 永远不可绕过。
9. **单据外产品（数量追溯）**：按 `barcode_new_product_policy`；`allow` 自动新建 move 拣 1 件，`warn` 走底栏确认。
10. **行选中可取消**：`set_active_move(move_id=False)` 清空选中，前端再次点击同一行即切换。
11. **下拉刷新**：只调用 `get_scan_state` 刷新数据，不重建向导；手势绑定在根节点（触摸 + 鼠标），列表需在顶部。
12. **提示条三行**：模式提示 / 操作提示 / 当前操作，无 ✕；深色模式正常提示仍为浅紫底。

---

## 6. 开发与调试工作流

```bash
# 启动（后台保活，HTTP 8071）
cd /run/media/max/DATA1/projects/odoo-dev/19.0 && setsid bash start_odoo.sh > /tmp/odoo.log 2>&1 &

# 改 SCSS / XML / JS 后：清资源包缓存 → 重启
venv/bin/python src/odoo/odoo-bin shell -c config/odoo.conf -d odoo19 --stop-after-init <<'EOF'
self.env.cr.execute("DELETE FROM ir_attachment WHERE name LIKE 'web.assets%'")
self.env.cr.commit()
EOF
pkill -9 -f odoo-bin && setsid bash start_odoo.sh > /tmp/odoo.log 2>&1 &

# 改 Python / 数据 / manifest 后：升级模块
venv/bin/python src/odoo/odoo-bin -c config/odoo.conf -d odoo19 --no-http --stop-after-init -u stock_barcodes_picking

# 校验资源是否真的编译进去（改完样式必查）
venv/bin/python src/odoo/odoo-bin shell -c config/odoo.conf -d odoo19 --no-http --stop-after-init <<'EOF'
b = self.env['ir.qweb']._get_asset_bundle('web.assets_web')
css = "".join(f.raw.decode(errors='ignore') for f in b.css())
print('样式已进包:', '#D0EDF0' in css)
EOF
```

- 只改样式/模板时**必须**清 `web.assets_web*` 附件，否则浏览器拿到旧包。
- XML 模板在 `static/src/`，属于**资源包**，改完不需要 `-u`，但要清缓存 + 重启。
- 浏览器验证用 `Ctrl+Shift+R`。

---

## 7. 踩坑与铁律

### 7.1 设计稿还原：像素采样优先于读 CSS

Pixso 导出的 HTML 经常把**多层半透明填充**压成"不透明渐变盖在色块上"，直接照抄 CSS 会得到完全错误的颜色（本项目已经踩过两次：信息框被还原成纯白 / `#404144`）。

**正确流程：**
1. 把设计稿目录用 `python3 -m http.server` 起起来，浏览器截图。
2. 用 PIL 采样目标图的**真实像素值**（取色块内部，避开文字和描边）。
3. 反推合成公式：`over(fg, alpha, bg)`，逐层算到与采样值误差 ≤ 3。
4. 用**合成后的不透明十六进制**写进 token，避免受本模块页面底色影响。

参考实现：信息框浅色 `#D0EDF0` = `teal(.2)` over 白；深色 `#38555B` = `teal(.2)` over `#404144`。

### 7.2 图标：直接搬设计稿 SVG，不手绘

- 设计稿 `image/*.svg` 原样复制到 `static/src/img/`，用 `<img src>` 引用。
- SVG 内 `fill` 是硬编码的，**不受 CSS 深色反转影响**，这正是我们要的。
- 当 SVG 同时包含"图标 + 按钮背景/阴影"（如 `Instance_34_xxx.svg`）时，只取 icon `path`，背景和阴影交给 CSS，否则无法跟随主题。
- 不要靠改 `viewBox` 手调图标位置——坐标系算错会直接变形（本项目踩过：返回/相机图标被改坏）。

### 7.3 Odoo 原生组件选择器要实测

`CogMenu` 在 Odoo 19 渲染成 `.o_cp_action_menus button`，**没有** `.o-dropdown` / `.dropdown-toggle` 类。凭经验写选择器会导致样式完全不生效。改原生组件前先在浏览器元素面板确认真实 DOM。

### 7.4 深色样式有两处，必须同步

| 位置 | 加载时机 |
|---|---|
| `picking_scan_app.scss` 内 `&[data-theme="dark"]` | 随亮色包一起 |
| `picking_scan_app.dark.scss` | `web.assets_web_dark`，Odoo color_scheme = dark |

只改一处会出现"切深色后一半对一半错"。

### 7.5 样式作用域要收窄

`o_scan_row` 同时被批号行和序列号行复用。要只改序列号行时必须靠模板上打标记类（本项目加了 `is-serial`），**不要**直接改公共类，否则批号行一起被重排。

### 7.6 XML 模板不要用文本工具整体重写

用 Write 覆盖 XML 容易把 `<?xml ...?>` 写成 `&lt;?xml`，导致 `-u` 直接中断。改完必须回读文件开头确认。

### 7.7 动画类需求优先"常驻态"

用户对"闪烁"类效果多次反复（先要 2 秒闪烁 → 改成常驻高亮）。实现时把"高亮"做成一个 class（`is-scanned`），闪烁只是可选的 `animation` 附加项，切换成本低。

### 7.8 新增 i18n 词条必须同步 `.pot`

Odoo 读取代码翻译时会把 `.pot` 合并进 `.po`：**po 里有、pot 里没有的 msgid 会被标记为 obsolete 并跳过**，表现为前端仍显示英文。
新增/修改 `env._()` 文案时，同时在 `i18n/stock_barcodes_picking.pot` 补同名 msgid（`#. odoo-python` + 对应 occurrence），再重启服务。

---

## 8. 当前开发进度（2026-11-17，v4.4 收尾）

### 本轮完成（扫码页重构收尾）

| 领域 | 状态 |
|---|---|
| 新拟态视觉（按钮/产品卡/批次下拉/行边框/顶部图标） | ✅ 按 Pixso「新拟态」页面走查完成 |
| 提示条三行布局 + 深色浅紫底 | ✅ |
| 数量追溯按包裹拆行 + 需求按包裹分配（总额固定） | ✅ |
| 数量追溯扫产品 = 自动 +1（未装包剩余行） | ✅ |
| 行 `+1` / 修改弹窗按行生效；数量追溯行无批次字段 | ✅ |
| 取消拣货：单件 + 多包裹选包弹窗 | ✅ |
| 取消拣货（批次号）：扫批次号取消 1 件 | ✅ |
| 扫描拆包：单件 + 多包裹选包弹窗（拆到未装包） | ✅ |
| 超拣 `warn`：底栏强制按钮（`pending_add`，按目标数量强制写入） | ✅ |
| 单据外产品（数量追溯）：按 `barcode_new_product_policy` 添加 | ✅ |
| 行选中再次点击取消 | ✅ |
| 下拉刷新 + 右上角刷新键 | ✅ |
| 批次/序列号列表项分隔线 | ✅ |
| 隐藏追溯产品的「未分配批次」占位行 | ✅ |

### 未做 / 待确认

- `TO-DO LIST.md`、`TO-DO LIST - UI重构.md` 中剩余项（以那两份为准）。
- 批次/序列号产品的**扫描拆包**仍按整行处理，未做单件+选包（当前需求只要求数量追溯）。
- 自动化浏览器回归未接入（登录态在自动化环境里不稳定），靠 `test_stock_barcodes_picking.py` + 手工刷新验证。
- 前端资源缓存：改 JS/XML/SCSS 后需浏览器强刷（资源包按文件 mtime 换版本）；排障时先确认页面加载的是最新 bundle。

---

## 9. 扩展指引

### 新增一种提示状态
1. 后端 `_set_message(type, text)` 增加新 `message_type`。
2. `picking_scan_app.js` 的 `alertClass` getter 加映射。
3. `picking_scan_app.scss` 加 `.o_scan_hintbar.alert-xxx`，亮/暗各一套 token。
4. 设计稿没有的色板必须找设计确认，不要自行发明。

### 新增一种卡片类型
1. 行数据统一由 `_get_scan_rows_v4()` / `_build_scan_row()` 产出；需要新分组时改这两处，不要把分组逻辑放前端。
2. XML 增卡片分支，并给行元素打独立标记类（避免污染 `o_scan_row`）。
3. 样式用标记类收窄，尺寸/配色对齐设计 token。
4. 后端 `get_scan_state` 快照要带上新分组需要的字段。

### 新增一个顶部/底部按钮
1. 优先复用 `.o_scan_key`（键帽样式），图标按钮 30×30。
2. 图标从设计稿 SVG 复制，`<img>` 引用；文字图标用 FontAwesome（颜色继承 `--scan-key-fg`）。
3. 点击一律 `t-on-click.stop`，避免冒泡到卡片选中逻辑。
4. 是否可用由 `canXxx` getter 统一判断，模板只渲染不判断。

---

## 10. 回归检查清单

改完 UI 至少手工过一遍：

- [ ] 亮色 / 深色各截一次图，信息框三态颜色与设计稿一致（正常提示深色也是浅紫底）
- [ ] 提示条三行：模式提示 / 操作提示 / 当前操作，均有内容时不重复、不串行
- [ ] 顶栏左右按钮为键帽样式、齿轮与刷新图标正确
- [ ] 扫码输入框能正常输入、回车提交、相机按钮可用
- [ ] 序列号卡默认折叠；点折叠条可展开/收起；批次项之间有 1px 分隔线
- [ ] 扫序列号 → 该行绿色高亮且常驻；扫另一个码 → 旧高亮消失
- [ ] 折叠态扫序列号 → 摘要行切换并高亮，且不自动展开
- [ ] 数量追溯：扫产品 +1、按包裹拆行、需求分配（10/4 → `0/6` + `4/4`）
- [ ] 数量追溯：`+1` / 修改只影响当前行；包名留空不清包裹
- [ ] 取消拣货 / 扫描拆包：单件生效；多包裹弹窗；取消弹窗不写入
- [ ] 点击产品行选中，再次点击取消选中
- [ ] 下拉刷新 / 右上刷新键：只刷新数据，选中状态保留
- [ ] `pkill` 重启后浏览器强刷无旧样式残留（先确认加载的是最新 bundle）

---

## 11. 相关资产索引

| 类型 | 位置 |
|---|---|
| 业务规则审计 | `RULES.md` |
| 功能待办 | `TO-DO LIST.md` |
| 界面重构待办 | `TO-DO LIST - UI重构.md` |
| 可复用 Skill | `.trae/skills/odoo19-barcode-wizard/SKILL.md`（Odoo 19 扫码向导通用骨架） |
| 项目经验库 | `/run/media/max/DATA1/projects/odoo-dev/lessons_learned.md` |
| 设计稿来源 | `/home/max/下载/html-设计文件 (23|24|2|3)/html`、`/home/max/下载/扫码设计/` |
| 后端测试 | `tests/test_stock_barcodes_picking.py` |
