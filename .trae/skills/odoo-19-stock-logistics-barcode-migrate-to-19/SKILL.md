---
name: odoo-19-stock-logistics-barcode-migrate-to-19
description: 当用户需要将 OCA stock-logistics-barcode 仓库的某个模块从 Odoo 18.0（或更早版本）迁移到 19.0 时使用此技能。覆盖视图语法、ORM API、JS 模块化、i18n、约束声明、Cog Menu、pre-commit 规则等 19.0 兼容性改造。触发词包括：迁移到 19、migrate to 19、18.0 到 19.0、Odoo 19 迁移、stock_barcodes 迁移、barcodes_generator 迁移、tree 改 list、view_mode、attrs 移除、_sql_constraints 改 Constraint、fields.Datetime.add、Command、api.model_create_multi、ESM、OWL、cogMenuRegistry、msgid 英文、pylint-odoo 19、pre-commit 19。
---

# odoo-19-stock-logistics-barcode-migrate-to-19

## 描述
为 OCA `stock-logistics-barcode` 仓库从 18.0 → 19.0 迁移提供具体改造清单与验证步骤。本技能只读、不直接修改源码；列出需要修改的项与示例，由实现任务执行。

## 使用场景
- 当用户问"这个模块怎么迁移到 19.0"时
- 当用户问"`<tree>` 标签是否还能用"时
- 当用户问"`_sql_constraints` 在 19.0 怎么写"时
- 当用户问"JS 怎么改成 ESM"时
- 当用户报告 pylint-odoo 19.0 报新规则时
- 当 CI test.yml 在 19.0 矩阵失败时
- 当用户要新增 19.0 模块需要遵循规范时

## 指令

### 1. 视图（XML）改造清单
- `<tree>` → `<list>`
- `view_mode="tree,form"` → `view_mode="list,form"`
- 移除 `attrs="{'readonly': [('state', '=', 'done')]}"`，改为 `readonly="state == 'done'"`
- 移除 `states="done"`，同上改为表达式求值
- 缩进必须 2 空格（pre-commit prettier 强制）
- 字段必须显式声明 `string` 属性
- Form 视图必须用 `<sheet>` 包裹
- 按钮放 `<header>` 或 `sheet` 顶部
- search 视图的 `<group>` 禁用 `expand` 属性（RNG 严格校验）
- search 视图必须添加常用筛选条件
- Group By 用 `<group string="Group By">` + `<filter context="{'group_by': 'field'}"/>`
- `widget="drag_handle"` → `widget="handle"`
- prettier-plugin-xml 会自动格式化，但语义改动必须手工

### 2. ORM 与 Python 改造清单
- `_sql_constraints = [("name", "check(...)", "msg")]` → `models.Constraint("name", "check(...)", "msg")`
- `fields.Datetime.add(datetime, hours=1)` → `datetime + timedelta(hours=1)`
- `@api.one` 已删除，改为普通方法或 `@api.model_create_multi`
- `@api.model_create_multi` 替代 `@api.model` 的 `create` 多条记录
- x2many 写入：`(0, 0, vals)` → `Command.create(vals)`、`(4, id)` → `Command.link(id)` 等
- `self.env['model'].sudo()` 在 Odoo 19 返回空记录集，`bool()` 为 False；判断模型可用用 `is not None`
- `models.Model._name = "..."` 仍可用，但新模型应同时声明 `_description`
- `field_name` 字段定义中不得使用 `stored=True`（错字），应为 `store=True`
- `@api.depends` 必须列出所有依赖字段，否则计算字段不更新
- `_compute_display_name` 直接赋值 `self.display_name = ...`，不返回值
- 空的 `except:` 块必须补日志记录
- 未使用的 import 必须清理（ruff 会报）

### 3. JS / 前端改造清单
- 文件用 ESM：`/** @odoo-module */` 注释开头，`import` 标准语法
- `@odoo/owl`、`@web/core/utils/hooks`、`@web/views/...` 等命名导入
- OWL 组件用 `setup()` 替代构造函数，`onMounted`/`onWillStart`/`useEffect` 钩子
- `this._rpc(...)` → `useService("orm")` 后 `this.orm.call(...)`
- `this.do_action(...)` → `useService("action")` 后 `this.action.doAction(...)`
- `this._super(...)` → `super.methodName(...)` 或在 `setup()` 中 `super.setup()`
- Cog Menu 注册：`registry.category("cogMenu").add("name", { Component, isAvailable })`，而非 `getStaticActionMenuItems`
- 删除调试用 `console.log`
- `eslint.config.cjs` 强制 jsdoc，新函数需补注释或加 `// eslint-disable-next-line`

### 4. i18n / 翻译改造清单
- `msgid` 必须用英文，中文走 `zh_CN.po`
- `_(u"中文")` → `_("English text")`
- 翻译文件 `i18n/*.po` 由 CI OCB 矩阵推送 `.pot` 后生成，勿手动改 `.pot`
- `en.po` 文件禁止存在（pre-commit forbidden-files hook）

### 5. manifest 改造清单
- `version` 必须是 `19.0.x.y.z` 格式
- `license` 字段必填，且在 `AGPL-3`/`LGPL-3`/`GPL-2`/`GPL-3`/`OPL-1` 之一
- `website` 必须是 `https://github.com/OCA/stock-logistics-barcode`（pre-commit `oca-fix-manifest-website` 自动修）
- `author` 必须包含 `Odoo Community Association (OCA)`
- `external_dependencies` 用 `{"python": [...], "bin": [...]}` 格式
- `assets` 段：`web.assets_backend` 用通配符 `*.esm.js` + 显式 `*.xml`
- `pre_init_hook`/`post_init_hook` 函数放 `hooks.py`，`__init__.py` 导入
- `development_status` 字段：`Alpha/Beta/Production/Stable`，CI `check-dev-status` 默认 `Beta`

### 6. 测试改造清单
- 测试基类：`TransactionCase` 或 `BaseCommon`（不发请求用 `BaseCommon`）
- `@tagged("post_install", "-at_install")` 仍是标准
- 用 `add_to_registry` 注入 fake model 时必须 `addClassCleanup` 清理
- `self.env.ref("...")` 引用模块数据需带模块前缀
- 断言用 `assertEqual`/`assertTrue`/`assertFalse`，避免 `assert x == y`（pylint 偏好）
- 测试类命名：`Test<ModuleName>`，文件名 `test_<feature>.py`

### 7. pre-commit / CI 改造清单
- `.pre-commit-config.yaml` 中 `rev` 用 OCA 推荐版本
- `pylint_odoo` 用 `--rcfile=.pylintrc-mandatory`（不可降级）+ `--rcfile=.pylintrc`（optional）
- `ruff`/`ruff-format` 用最新 stable
- `prettier` 用 `prettier@3.6.2` + `@prettier/plugin-xml@3.4.2`
- `eslint` 用 `eslint@9.35.0` + `eslint-plugin-jsdoc`
- `.github/workflows/test.yml` 矩阵用 `py3.10-odoo19.0` 与 `py3.10-ocb19.0`
- `OCA_ENABLE_CHECKLOG_ODOO=1` 启用 checklog

### 8. 迁移步骤建议（分阶段）
1. **阶段 1：视图语法**（机械改造，pre-commit 大部分能自动修）
   - 跑 `pre-commit run --all-files`，让 prettier/ruff 自动改
   - 手工改 `<tree>` → `<list>`、`view_mode`、`attrs` → 表达式
2. **阶段 2：ORM API**
   - `_sql_constraints` → `models.Constraint`
   - `fields.Datetime.add` → `timedelta`
   - x2many `(0,0,vals)` → `Command.create(vals)`
3. **阶段 3：JS ESM**
   - IIFE 改 ESM
   - `this._rpc` → `useService`
4. **阶段 4：测试**
   - 跑 `run_tests.sh --install <module>`
   - 修夹具与断言
5. **阶段 5：i18n 与 manifest**
   - msgid 改英文
   - manifest 字段补全
6. **阶段 6：CI 验证**
   - 本地跑完整 pre-commit
   - 推 PR 看 CI

### 9. 验证清单
- [ ] `pre-commit run --all-files` 全绿
- [ ] `run_tests.sh --install <module>` 测试通过
- [ ] 浏览器手动测试扫码界面无报错
- [ ] `__manifest__.py` 字段完整
- [ ] 无 `en.po` 文件
- [ ] 无 `.rej` 文件
- [ ] 无 debug 语句
- [ ] `msgid` 全英文
- [ ] 视图无 `<tree>` 残留
- [ ] 视图无 `attrs` 残留
- [ ] `_sql_constraints` 改为 `models.Constraint`
- [ ] JS 文件都是 ESM（`/** @odoo-module */`）

### 10. 关键参考文件
- 19.0 已迁移范本：[stock_barcodes/__manifest__.py](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/__manifest__.py)
- pre-commit 配置：[.pre-commit-config.yaml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/.pre-commit-config.yaml)
- pylint 配置：[.pylintrc-mandatory](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/.pylintrc-mandatory)
- CI 流水线：[test.yml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/.github/workflows/test.yml)
- 19.0 视图范本：[stock_barcodes_action_view.xml](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/views/stock_barcodes_action_view.xml)
- 19.0 JS 范本：[form_controller.esm.js](file:///run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode/stock_barcodes/static/src/views/form/form_controller.esm.js)

## 示例

**用户问**："为什么我的视图报 'View definition is invalid'？"

**回答**：检查 search 视图的 `<group>` 是否有 `expand` 属性。Odoo 19 RNG 严格校验禁止 `expand`。改为：
```xml
<group string="Group By">
  <filter name="group_by_location" context="{'group_by': 'location_id'}"/>
</group>
```

**用户问**："`_sql_constraints` 在 19.0 怎么写？"

**回答**：
```python
# 旧
_sql_constraints = [
    ("unique_barcode", "unique(barcode)", "Barcode must be unique!"),
]

# 新（19.0）
models.Constraint(
    "unique_barcode",
    "unique(barcode)",
    "Barcode must be unique!",
)
```
注意 `models.Constraint` 不是列表，是类属性，每个约束一个实例。

**用户问**："JS 怎么改成 ESM？"

**回答**：
```javascript
/** @odoo-module */
// 旧 IIFE
odoo.define("mymodule", function (require) {
    var Widget = require("web.Widget");
    var MyWidget = Widget.extend({...});
    return MyWidget;
});

// 新 ESM
import {Component} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";

export class MyComponent extends Component {
    setup() {
        this.orm = useService("orm");
    }
    async doSomething() {
        await this.orm.call("model.name", "method", []);
    }
}
```
