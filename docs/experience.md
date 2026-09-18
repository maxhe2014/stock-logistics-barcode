# stock-logistics-barcode 经验总结（Odoo 19.0 / OCA）

> 维护者：AI 知识库
> 生成日期：2026-09-18
> 适用版本：Odoo 19.0
> 仓库：OCA/stock-logistics-barcode（分支 19.0）
> 项目根目录：`/run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode`

---

## 1. 项目概览

本仓库是 OCA（Odoo Community Association）维护的"条码与库存物流"模块集合，针对 Odoo 19.0 分支。仓库提供：

- 为任意模型/产品生成条码（基于规则的 GS1/EAN13/Code128 等）
- 为产品扩展多条码支持（一个产品绑定多个条码）
- 在库存作业（picking/inventory）中通过扫码完成扫码引导式作业
- 一个客户端扫码动作（client action）组件，可在任意视图触发扫码

仓库级许可证：AGPL-3.0（见 `LICENSE`）。各模块的 `__manifest__.py` 中可单独声明许可证（如 `web_ir_actions_client_scan` 使用 LGPL-3）。

OCA CI 使用 `ghcr.io/oca/oca-ci/py3.10-odoo19.0:latest` 与 `ocb19.0` 镜像并行测试，PG 13。

---

## 2. 模块清单与职责

| 模块 | 版本 | 许可证 | 依赖 | 职责 |
|---|---|---|---|---|
| `barcodes_generator_abstract` | 19.0.1.0.0 | AGPL-3 | `barcodes` | 抽象层：基于 `barcode.rule` 为任意模型生成条码（sequence/manual）。外部 Python 依赖 `python-barcode`。 |
| `barcodes_generator_product` | 19.0.1.0.0 | AGPL-3 | `barcodes_generator_abstract`, `product` | 将抽象生成器落地到 `product.template`/`product.product`，按规则生成产品条码。 |
| `product_multi_barcode` | 19.0.1.0.0 | AGPL-3 | `product`（核心 `barcodes`） | 在产品上挂多条码（`product.barcode.multi`），`post_init_hook` 迁移原 `barcode` 字段。 |
| `stock_barcodes` | 19.0.1.0.0 | AGPL-3 | `barcodes`, `stock`, `web_widget_numeric_step`, `web`, `mail` | **核心模块**：库存作业扫码界面（picking/inventory），引导式/手动输入模式、lot/包装自动识别、`pre_init_hook` 给 `stock_move_line.barcode_scan_state` 与 `stock_move.barcode_backorder_action` 加列。 |
| `web_ir_actions_client_scan` | 19.0.1.0.0 | LGPL-3 | `barcodes` | 添加 `ir.actions.client` 扫码动作，可在任意视图绑定扫码触发器。 |

> 注：仓库根 `README.md` 的 addon 表是 pre-commit bot 自动维护的，目前只列了前 3 个。新增/迁移模块后，bot 会自动补全（见 `.pre-commit-config.yaml` 中的 `oca-gen-addon-readme`）。

---

## 3. 目录结构说明

```
stock-logistics-barcode/                    # 仓库根
├── LICENSE                                  # AGPL-3
├── README.md                                # OCA 自动生成，addon 表由 pre-commit 维护
├── requirements.txt                         # 由 manifest 自动生成：python-barcode
├── .pre-commit-config.yaml                  # ruff/ruff-format, pylint_odoo, prettier+plugin-xml, eslint, oca-checks
├── .pylintrc / .pylintrc-mandatory          # pylint-odoo 配置（mandatory 不可降级）
├── .ruff.toml                               # ruff 行内规则
├── eslint.config.cjs / prettier.config.cjs  # 前端规则（bracketSpacing=false, printWidth=88）
├── checklog-odoo.cfg                        # OCA checklog 配置
├── setup/                                   # OCA 打包元数据（_metapackage 等）
├── .github/workflows/
│   ├── pre-commit.yml
│   ├── stale.yml
│   └── test.yml                             # OCA 标准测试流水线
├── barcodes_generator_abstract/
│   ├── models/                              # barcode.rule 扩展、abstract mixin
│   ├── security/res_groups.xml              # "Barcode Generation" 用户组
│   ├── views/                               # barcode_rule、barcode_nomenclature、菜单
│   ├── tests/                               # 用 add_to_registry 注入 fake model 测试
│   └── demo/                                # res_users, barcode_rule demo
├── barcodes_generator_product/
│   ├── models/                              # product.template/product.product 扩展
│   ├── views/                               # product 视图加 barcode 生成按钮
│   └── tests/
├── product_multi_barcode/
│   ├── models/                              # product.barcode.multi, product.product 扩展
│   ├── hooks.py                             # post_init_hook 迁移原 barcode
│   ├── security/ir.model.access.csv
│   ├── views/                               # product/product_template 视图
│   └── tests/
├── stock_barcodes/                          # 核心模块
│   ├── __init__.py                          # 加载 models/wizard/reports + pre_init_hook
│   ├── __manifest__.py
│   ├── hooks.py                             # pre_init_hook: 加 barcode_scan_state / barcode_backorder_action 列
│   ├── models/
│   │   ├── barcode_events_mixin.py          # 扩展 barcodes.barcode_events_mixin，加 bus_bus 推送
│   │   ├── stock_barcodes_action.py         # 扫码界面可用的"动作"配置（绑定 ir.actions.act_window）
│   │   ├── stock_barcodes_option.py         # 扫码选项组（option.group）+ 步骤字段配置
│   │   ├── stock_move.py                    # barcode_backorder_action 字段
│   │   ├── stock_move_line.py               # barcode_scan_state 字段
│   │   ├── stock_picking.py                 # action_barcode_scan 入口
│   │   ├── stock_picking_type.py            # picking.type 绑定 option_group
│   │   └── stock_quant.py                   # quant 扫码支持
│   ├── wizard/
│   │   ├── stock_barcodes_read.py           # Abstract wizard 基类（核心扫码逻辑）
│   │   ├── stock_barcodes_read_picking.py   # picking 扫码 wizard
│   │   ├── stock_barcodes_read_inventory.py # inventory 扫码 wizard
│   │   ├── stock_barcodes_read_todo.py      # 待处理移动行 todo
│   │   ├── stock_barcodes_candidate_picking.py # 多候选 picking 选择
│   │   ├── stock_production_lot.py          # 扫码即时创建 lot
│   │   └── *_views.xml                      # 各 wizard 视图
│   ├── reports/                             # barcode_actions 报表
│   ├── security/ir.model.access.csv         # stock.group_stock_user / stock.group_stock_manager
│   ├── data/                                # 默认 option_group、action 数据
│   ├── views/                               # stock_picking、stock_location、菜单等
│   ├── static/src/
│   │   ├── views/
│   │   │   ├── actions/                     # 主菜单 client action
│   │   │   ├── form/                        # 自定义 FormController/FormView
│   │   │   ├── kanban/                      # 自定义 Kanban Record/Renderer/View
│   │   │   └── views.esm.js / view_compiler.esm.js
│   │   ├── widgets/                         # numeric_step、view_button、boolean_toggle
│   │   ├── utils/                           # barcode_handler_field、barcodes_models_utils
│   │   ├── scss/                            # barcode.scss、stock.scss
│   │   ├── sounds/                          # 扫码音效
│   │   ├── img/
│   │   └── docs/                            # PDF 文档（barcodes_actions.pdf 等）
│   └── tests/
│       ├── common.py                        # TestCommonStockBarcodes（TransactionCase）
│       ├── test_stock_barcodes.py           # 通用扫码测试
│       ├── test_stock_barcodes_new_lot.py   # 扫码即时建 lot
│       └── test_stock_barcodes_picking.py   # picking 扫码流程
└── web_ir_actions_client_scan/
    ├── static/src/                          # client action 注册
    └── (无 python models)
```

---

## 4. 环境与依赖

### 4.1 Python 依赖
- `python-barcode`（由 `barcodes_generator_abstract` 声明，仓库根 `requirements.txt` 自动生成）

### 4.2 Odoo / 数据库
- Odoo 19.0 源码：`/run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo`
- venv：`/run/media/max/DATA1/projects/odoo-dev/19.0/venv`
- 配置：`/run/media/max/DATA1/projects/odoo-dev/19.0/config/odoo.conf`
  - `http_port = 8071`
  - `db_name = odoo19`
  - `addons_path` 已包含 `…/addons/stock-logistics-barcode`（与 dingtalk、queue、web 并列）
  - `dev_mode = reload`（仅前端资源热更；改 `.py` 仍需重启进程）
  - `server_wide_modules = web,queue_job`

### 4.3 硬件依赖
- **扫码枪**：键盘模拟型（HID）扫码枪即可。`barcodes.barcode_events_mixin` 监听 `barcode_scanned` 事件，无需驱动。
- **无打印机依赖**：报表走标准 `ir.actions.report`，可外接标签打印机。

### 4.4 已知限制
- 钉钉的 `dingtalk` 系列模块与本仓库无依赖关系；不要混淆两者。
- OCA CI 镜像与本地的 venv 版本可能不同步；本地通过 `shared/run_tests.sh` 跑测试用本地 venv。

---

## 5. 常用命令

### 5.1 启动 Odoo（开发）
```bash
# 优雅停掉旧进程后重启（dev_mode=reload 不会重载 .py）
pkill -TERM -f "odoo-bin -c .*odoo.conf" || true
setsid nohup /run/media/max/DATA1/projects/odoo-dev/19.0/venv/bin/python \
  /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo-bin \
  -c /run/media/max/DATA1/projects/odoo-dev/19.0/config/odoo.conf \
  >> /run/media/max/DATA1/projects/odoo-dev/19.0/logs/odoo.log 2>&1 &
```

### 5.2 安装/更新模块
```bash
# 安装核心模块（含依赖）
cd /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d odoo19 \
  -i stock_barcodes --stop-after-init

# 更新
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d odoo19 \
  -u stock_barcodes --stop-after-init
```

### 5.3 运行测试（项目级脚本）
```bash
# 项目根的入口（推荐）
/run/media/max/DATA1/projects/odoo-dev/19.0/run_tests.sh --install stock_barcodes

# 或直接调底层
cd /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d odoo19 \
  --test-enable --test-tags /stock_barcodes --stop-after-init \
  -i stock_barcodes
```

### 5.4 仅跑 lint / pre-commit
```bash
# pylint-odoo
/run/media/max/DATA1/projects/odoo-dev/19.0/run_tests.sh --lint \
  /run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode

# pre-commit（仓库根有 .pre-commit-config.yaml）
cd /run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode
pre-commit run --all-files
```

### 5.5 资源重新编译（前端调试必用）
```
http://127.0.0.1:8071/web/assets/debug
```
或浏览器隐身 + `Ctrl+Shift+R`。Odoo 19 资产缓存是 UI 异常最常见原因。

---

## 6. 关键实现

### 6.1 扫码事件链路
1. **前端监听**：`barcodes.barcode_events_mixin`（核心 `barcodes` 模块）监听键盘输入，触发 `barcode_scanned` 事件。
2. **后端入口**：`wiz.stock.barcodes.read`（AbstractModel）的 `_on_barcode_scanned` 方法。
3. **分发**：`stock_barcodes_read.py` 中根据 `option_group_id` 配置的步骤（step）和字段，依次匹配 location/product/lot/packaging/package。
4. **落库**：通过 `stock_move_line`/`stock_move` 的扩展字段 `barcode_scan_state` 跟踪每行是否完成。
5. **回写 UI**：`barcode_events_mixin.send_bus_done` 通过 `bus.bus` 推送 `stock_barcodes_form_update` channel，前端 `StockBarcodesFormController` 监听并刷新。

### 6.2 引导式扫码（Guided Mode）
- `stock.barcodes.option.group.barcode_guided_mode = "guided"` 启用。
- `option_ids` 配置每步字段（`location_id`/`product_id`/`lot_id`/`packaging_id`），`to_scan=True` 控制是否需要扫码，`required=True` 控制是否必填。
- `wiz.stock.barcodes.read.todo` 维护待处理列表，`group_key_for_todo_records` 支持自定义分组键。

### 6.3 Lot / 包装 / 多条码
- **Lot 即时创建**：`stock_production_lot.py` 提供 `wiz.stock.barcodes.new.lot`，扫码时若 lot 不存在且 `option_group.create_lot=True` 则即时创建。
- **包装识别**：通过 `product.packaging.barcode` 反查包装，自动填 `packaging_id` 与 `product_qty`。
- **多条码**：`product_multi_barcode` 引入 `product.barcode.multi` 表，扫码时优先匹配该表。
- **GS1**：依赖核心 `barcodes` 模块的 nomenclature 解析（`(01)...(10)...` 等应用标识符）。

### 6.4 前端架构（OWL）
- `form/form_controller.esm.js`：扩展 `FormController`，加 `bus_service` 监听、隐藏控制面板（`control_panel_hidden` context）。
- `form/form_view.esm.js`：注册自定义 FormView。
- `kanban/`：自定义 Kanban Record/Renderer/View，用于动作选择卡片视图。
- `widgets/numeric_step`：在 `web_widget_numeric_step` 之后 `after` 注入，覆盖扫码界面的数字步进组件。
- `utils/barcode_handler_field.esm.js`：字段级条码处理工具。

### 6.5 数据库迁移
- `stock_barcodes/hooks.py` 的 `pre_init_hook` 直接 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，绕过 ORM 加列（性能与幂等考虑）。
- `product_multi_barcode/hooks.py` 的 `post_init_hook` 将原 `product.product.barcode` 迁移到 `product.barcode.multi`。

---

## 7. 配置与权限

### 7.1 权限组
- `stock.group_stock_user`：扫码 wizard 读写、option_group 读写。
- `stock.group_stock_manager`：`stock.barcodes.action` 的创建/编辑/删除、报表管理。
- `barcodes_generator_abstract` 自定义 `Barcode Generation` 组（见 `security/res_groups.xml`）。

### 7.2 关键配置点
- **`stock.picking.type.barcode_option_group_id`**：每个 picking 类型绑定一个 option_group，决定扫码行为。
- **`stock.barcodes.option.group`** 字段速查：
  - `manual_entry` / `manual_entry_field_focus`：手动输入模式默认值与聚焦字段
  - `confirmed_moves`：允许未预留移动
  - `auto_put_in_pack`：扫码验证前自动打包
  - `auto_lot`：自动按先进先出选 lot
  - `create_lot`：扫码即时建 lot
  - `allow_negative_quant`：允许负库存
  - `fill_fields_from_lot` / `ignore_quant_location`：lot 反填与位置忽略
  - `group_key_for_todo_records`：自定义 todo 分组键
- **`stock.barcodes.action`**：扫码界面顶部"动作"按钮，绑定 `ir.actions.act_window` + `barcode` + `key_shortcut`，可扫码或快捷键触发。

---

## 8. 测试与 CI

### 8.1 本地测试
- 测试基类：`TransactionCase`（`stock_barcodes/tests/common.py` 的 `TestCommonStockBarcodes`）。
- `barcodes_generator_abstract` 使用 `BaseCommon` + `add_to_registry` 注入 `res.users.tester` 等 fake model，测完用 `addClassCleanup` 清理。
- 测试分类：`@tagged("post_install", "-at_install")`，必须 `-i` 安装后再跑。

### 8.2 CI（`.github/workflows/test.yml`）
- 矩阵：`Odoo` + `OCB` 两个镜像，`OCB` 矩阵负责 `makepot` 推送 `.pot` 翻译。
- 步骤：`oca_install_addons` → `manifestoo check-licenses` → `manifestoo check-dev-status --default-dev-status=Beta` → `oca_init_test_database` → `oca_run_tests`。
- 环境变量 `OCA_ENABLE_CHECKLOG_ODOO=1` 启用 checklog。
- `unreleased-deps` job：拒绝 `requirements.txt` 中的 URL/相对路径依赖。

### 8.3 代码质量门禁
- pre-commit：`ruff --fix`、`ruff-format`、`pylint_odoo`（mandatory 不可降级）、`prettier`（含 plugin-xml）、`eslint`、`oca-checks-odoo-module`、`oca-checks-po`、`oca-gen-addon-readme`、`oca-gen-external-dependencies`、`oca-fix-manifest-website`、`oca-update-pre-commit-excluded-addons`。
- 禁止：`en.po` 文件、`.rej` 文件、debug 语句、混合换行符。

---

## 9. 常见问题与解决方案

| 现象 | 原因 | 解决 |
|---|---|---|
| 扫码界面无反应 | 资产缓存未更新 | 访问 `/web/assets/debug` 重新编译，浏览器隐身 + `Ctrl+Shift+R` |
| 扫码后字段未填 | `option_group` 配置错误（`to_scan=False` 或 `required=False` 但步骤顺序不对） | 检查 `stock.barcodes.option` 的 `step` 与 `field_name`，对照 `FIELDS_NAME` 映射 |
| 扫 lot 报 "not found" | lot 不存在且 `create_lot=False` | 在 option_group 勾选 `create_lot`，或预先建 lot |
| 负库存报错 | `allow_negative_quant=False` | 在 option_group 勾选 `allow_negative_quant` |
| `pre_init_hook` 失败 | 数据库已有 `barcode_scan_state` 列但类型不符 | 手动 `ALTER TABLE stock_move_line DROP COLUMN barcode_scan_state` 后重装 |
| 引导模式不显示 todo | `source_pending_moves` 配置错（`move_line_ids` vs `move_ids`） | 详细操作用 `move_line_ids`，操作用 `move_ids` |
| `bus.bus` 不推送 | 多 worker 或 `gevent` 未启动 | 检查 `server_wide_modules` 与 `limit_time_real`，扫码界面用 longpolling |
| `pylint_odoo` mandatory 失败 | manifest `license` 缺失或 `website` 错 | 运行 `pre-commit run oca-fix-manifest-website --all-files` 自动修 |
| `.pot` 提交冲突 | 多分支生成 | 仅在 OCB 矩阵 + push 事件 + OCA 仓库时由 CI 推送，本地勿手动改 |

---

## 10. 升级/迁移注意事项

### 10.1 从 18.0 迁移到 19.0
- **视图**：`<tree>` → `<list>`；`view_mode="tree,form"` → `view_mode="list,form"`；删除 `attrs`，改用 `readonly/required/invisible` 直接求值；XML 缩进 2 空格；字段必须显式 `string`；search 视图 `<group>` 不可加 `expand` 属性。
- **ORM**：`_sql_constraints` → `models.Constraint(...)`；`fields.Datetime.add()` → `timedelta`；`@api.model_create_multi` 替代 `_create`；x2many 写入用 `Command` 命名空间。
- **JS**：`@odoo-module` 注释保留；ESM 标准导入；`useService` 替代 `this._rpc`；OWL `setup()` 替代构造函数。
- **i18n**：`msgid` 用英文，中文走 `zh_CN.po`。
- **Cog Menu**：Odoo 19 通过 `cogMenuRegistry` 注册（非 `getStaticActionMenuItems`）。

### 10.2 卸载/重装
- 卸载 `stock_barcodes` 后，`barcode_scan_state`/`barcode_backorder_action` 列会随模型清理；若残留，手动 `ALTER TABLE ... DROP COLUMN`。
- `product_multi_barcode` 卸载后，原 `barcode` 字段不会回填，需手动从 `product.barcode.multi` 同步。

### 10.3 数据库迁移脚本
- 模块内 `migrations/` 子目录（若有）按版本号命名，OCA 标准做法；本仓库当前 19.0.1.0.0 无独立迁移脚本，依赖 `pre_init_hook`/`post_init_hook`。

---

## 11. 相关 SKILL 索引

| SKILL 名称 | 路径 | 用途 |
|---|---|---|
| `odoo-19-stock-logistics-barcode-module-overview` | `.trae/skills/odoo-19-stock-logistics-barcode-module-overview/SKILL.md` | 项目结构与模块职责速查 |
| `odoo-19-stock-logistics-barcode-run-tests` | `.trae/skills/odoo-19-stock-logistics-barcode-run-tests/SKILL.md` | 本地与 CI 测试执行 |
| `odoo-19-stock-logistics-barcode-debug-scanner` | `.trae/skills/odoo-19-stock-logistics-barcode-debug-scanner/SKILL.md` | 扫码功能调试与排错 |
| `odoo-19-stock-logistics-barcode-migrate-to-19` | `.trae/skills/odoo-19-stock-logistics-barcode-migrate-to-19/SKILL.md` | 从 18.0 迁移到 19.0 |

---

## 12. 变更记录

| 日期 | 执行者 | 内容 |
|---|---|---|
| 2026-09-18 | AI | 初始创建：项目侦察、模块清单、目录结构、环境、命令、关键实现、配置、测试、常见问题、迁移、SKILL 索引 |
