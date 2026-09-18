---
name: odoo-19-stock-logistics-barcode-module-overview
description: 当用户需要了解 OCA stock-logistics-barcode 仓库（Odoo 19.0）的模块结构、职责划分、依赖关系、目录布局或快速定位某个功能属于哪个模块时使用此技能。触发词包括：stock-logistics-barcode、stock_barcodes、barcodes_generator_abstract、barcodes_generator_product、product_multi_barcode、web_ir_actions_client_scan、OCA 条码、库存扫码、barcode 生成、多条码、扫码动作、模块清单、目录结构、模块依赖、模块职责。
---

# odoo-19-stock-logistics-barcode-module-overview

## 描述
为 OCA `stock-logistics-barcode` 仓库（Odoo 19.0 分支）提供模块清单、职责、依赖关系与目录结构速查。本技能只读、不修改任何源码。

## 使用场景
- 当用户问"这个仓库里有哪些模块"时
- 当用户问"`stock_barcodes` 模块是干什么的"时
- 当用户问"扫码功能在哪个模块"时
- 当用户问"`barcodes_generator_abstract` 和 `barcodes_generator_product` 有什么区别"时
- 当用户需要根据功能定位文件路径时
- 当用户准备安装/迁移/升级某个模块需要查依赖时

## 指令

### 1. 确认仓库根路径
仓库根固定为：
`/run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode`

### 2. 模块清单速查
仓库包含 5 个模块：

| 模块 | 版本 | 许可证 | 依赖 | 职责 |
|---|---|---|---|---|
| `barcodes_generator_abstract` | 19.0.1.0.0 | AGPL-3 | `barcodes` | 抽象层：基于 `barcode.rule` 为任意模型生成条码。Python 依赖 `python-barcode`。 |
| `barcodes_generator_product` | 19.0.1.0.0 | AGPL-3 | `barcodes_generator_abstract`, `product` | 产品条码生成器，扩展 `product.template`/`product.product`。 |
| `product_multi_barcode` | 19.0.1.0.0 | AGPL-3 | `product` | 产品多条码支持，`post_init_hook` 迁移原 `barcode` 字段。 |
| `stock_barcodes` | 19.0.1.0.0 | AGPL-3 | `barcodes`, `stock`, `web_widget_numeric_step`, `web`, `mail` | **核心模块**：库存作业扫码界面（picking/inventory），引导式/手动模式、lot/包装识别、`pre_init_hook` 加列。 |
| `web_ir_actions_client_scan` | 19.0.1.0.0 | LGPL-3 | `barcodes` | 客户端扫码动作，可在任意视图绑定扫码触发器。 |

### 3. 功能定位对照
| 用户需求 | 去哪个模块看 |
|---|---|
| 扫码枪在 picking 上扫码 | `stock_barcodes/wizard/stock_barcodes_read_picking.py` |
| 扫码枪在 inventory 上扫码 | `stock_barcodes/wizard/stock_barcodes_read_inventory.py` |
| 配置扫码步骤（先扫 location 还是 product） | `stock_barcodes/models/stock_barcodes_option.py` + `data/stock_barcodes_option.xml` |
| 扫码界面顶部"动作"按钮配置 | `stock_barcodes/models/stock_barcodes_action.py` |
| 扫码即时创建 lot | `stock_barcodes/wizard/stock_production_lot.py` |
| 前端扫码界面自定义 | `stock_barcodes/static/src/views/form/` 与 `views/kanban/` |
| 一个产品挂多个条码 | `product_multi_barcode/models/` |
| 按规则自动生成条码 | `barcodes_generator_abstract/` + `barcodes_generator_product/` |
| 在任意视图加扫码触发 | `web_ir_actions_client_scan/` |
| bus_bus 推送刷新 | `stock_barcodes/models/barcode_events_mixin.py` + `static/src/views/form/form_controller.esm.js` |

### 4. 目录结构
参考 `docs/experience.md` 第 3 节获取完整目录树。要点：
- Python 代码在 `models/` 与 `wizard/`
- 视图在 `views/` 与 `wizard/*_views.xml`
- 前端在 `static/src/`（ESM JS + XML + SCSS）
- 测试在 `tests/`（`common.py` 是基类）
- 数据在 `data/`（默认 option_group、action）
- 安全在 `security/ir.model.access.csv` + `security/res_groups.xml`

### 5. 依赖与权限
- 权限组：`stock.group_stock_user`（扫码）、`stock.group_stock_manager`（action 配置/报表）
- `barcodes_generator_abstract` 自带 `Barcode Generation` 组
- 安装顺序：先装 `barcodes_generator_abstract` 再装 `barcodes_generator_product`
- `stock_barcodes` 装时 `pre_init_hook` 给 `stock_move_line`/`stock_move` 加列
- `product_multi_barcode` 装时 `post_init_hook` 迁移原 barcode

### 6. 输出建议
- 回答模块职责时引用具体文件路径（用 `file:///` 链接）
- 涉及多模块交互时画简单依赖图
- 涉及许可证时显式区分 AGPL-3 与 LGPL-3
- 不要修改任何源码；如需修改，提示用户切换到对应的实现任务

## 示例

**用户问**："扫码功能在哪个文件？"

**回答**：核心扫码逻辑在 [stock_barcodes_read.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read.py)（Abstract 基类），picking 专用逻辑在 [stock_barcodes_read_picking.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read_picking.py)，inventory 专用在 [stock_barcodes_read_inventory.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/wizard/stock_barcodes_read_inventory.py)。

**用户问**："这仓库有 GS1 支持吗？"

**回答**：GS1 解析依赖核心 `barcodes` 模块的 nomenclature（应用标识符 `(01)`/`(10)` 等），本仓库不重复实现，只在 [barcodes_generator_abstract](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/barcodes_generator_abstract) 中扩展生成规则。
