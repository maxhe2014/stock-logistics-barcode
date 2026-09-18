---
name: odoo-19-stock-logistics-barcode-run-tests
description: 当用户需要在本地或 CI 环境为 OCA stock-logistics-barcode 仓库（Odoo 19.0）运行测试、安装/更新模块测试、运行 pre-commit、pylint-odoo 检查，或排查测试失败原因时使用此技能。触发词包括：运行测试、跑测试、test、pytest、pre-commit、pylint、pylint-odoo、lint、stock_barcodes 测试、barcodes_generator 测试、oca_run_tests、oca_install_addons、test-tags、--test-enable、--stop-after-init、CI 流水线、test.yml、install_test、unreleased-deps。
---

# odoo-19-stock-logistics-barcode-run-tests

## 描述
提供 OCA `stock-logistics-barcode` 仓库（Odoo 19.0）的本地测试、lint、CI 排错指令。本技能只读不修改源码。

## 使用场景
- 当用户问"怎么跑 stock_barcodes 的测试"时
- 当用户问"本地怎么验证模块能装上"时
- 当用户问"pylint-odoo 报错了怎么修"时
- 当用户问"pre-commit 失败怎么办"时
- 当 CI test.yml 失败需要本地复现时
- 当用户要新增测试用例但不知道测试基类怎么用时

## 指令

### 1. 环境前置检查
- venv：`/run/media/max/DATA1/projects/odoo-dev/19.0/venv`（必须存在 `bin/activate`）
- Odoo 源码：`/run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo/odoo-bin`
- 配置：`/run/media/max/DATA1/projects/odoo-dev/19.0/config/odoo.conf`（`addons_path` 已含 `stock-logistics-barcode`）
- Postgres 必须运行：`pg_isready -q` 应静默通过
- Python 依赖：`pip install python-barcode`（已声明在 `requirements.txt`）

环境自检：
```bash
/run/media/max/DATA1/projects/odoo-dev/19.0/run_tests.sh --check-env
```

### 2. 安装并测试单个模块
```bash
# 推荐入口（项目级脚本，会创建临时库 ot_19.0_<pid>）
/run/media/max/DATA1/projects/odoo-dev/19.0/run_tests.sh --install stock_barcodes

# 等价手动命令（在 odoo 源码目录执行）
cd /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d odoo19 \
  -i stock_barcodes --test-enable --test-tags "/stock_barcodes" \
  --stop-after-init 2>&1 | tee ../../logs/test_stock_barcodes.log
```

各模块测试命令替换模块名即可：
- `barcodes_generator_abstract`
- `barcodes_generator_product`
- `product_multi_barcode`
- `stock_barcodes`
- `web_ir_actions_client_scan`（无 tests 目录，仅安装测试）

### 3. 仅更新已安装模块并跑测试
```bash
cd /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d odoo19 \
  -u stock_barcodes --test-enable --test-tags "/stock_barcodes" \
  --stop-after-init
```

### 4. 测试基类与用例分布
- `stock_barcodes/tests/common.py` → `TestCommonStockBarcodes(TransactionCase)`：创建 option_group、location、product（带 packaging/barcode）、lot、quant、wizard 实例。
- `stock_barcodes/tests/test_stock_barcodes.py` → 通用扫码：location/product/packaging/lot/manual_entry/not_found/clean。
- `stock_barcodes/tests/test_stock_barcodes_new_lot.py` → 扫码即时建 lot。
- `stock_barcodes/tests/test_stock_barcodes_picking.py` → picking 扫码完整流程。
- `barcodes_generator_abstract/tests/` → 用 `BaseCommon` + `add_to_registry` 注入 fake model（`res.users.tester`、`barcode.rule` 扩展），`addClassCleanup` 清理。
- 所有测试都 `@tagged("post_install", "-at_install")`，必须 `-i` 安装后再跑。

新增测试时：
1. 继承 `TestCommonStockBarcodes`
2. 在 `setUpClass` 中扩展夹具（product/lot/quant）
3. 通过 `self.action_barcode_scanned(self.wiz_scan, "<barcode>")` 模拟扫码
4. 断言 wizard 字段或 stock.move.line 状态

### 5. Lint 与 pre-commit
```bash
# pylint-odoo（项目根有 .pylintrc 与 .pylintrc-mandatory）
cd /run/media/max/DATA1/projects/odoo-dev/19.0/addons/stock-logistics-barcode
pre-commit run pylint_odoo --all-files

# 完整 pre-commit（ruff + ruff-format + pylint + prettier + eslint + oca-checks）
pre-commit run --all-files

# 仅 ruff
pre-commit run ruff --all-files
pre-commit run ruff-format --all-files
```

`.pylintrc-mandatory` 不可降级，必须修复；`.pylintrc` 是 optional（`--exit-zero`）。

### 6. CI 排错（`.github/workflows/test.yml`）
CI 矩阵：`Odoo`（oca-ci/py3.10-odoo19.0）+ `OCB`（oca-ci/py3.10-ocb19.0，负责 makepot）。
CI 步骤本地复现：
```bash
# 模拟 oca_install_addons + oca_run_tests
# 1. 安装所有模块到测试库
createdb ot_ci_test
cd /run/media/max/DATA1/projects/odoo-dev/19.0/src/odoo
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d ot_ci_test \
  -i barcodes_generator_abstract,barcodes_generator_product,product_multi_barcode,stock_barcodes,web_ir_actions_client_scan \
  --stop-after-init
# 2. 跑全部测试
../venv/bin/python odoo-bin -c ../../config/odoo.conf -d ot_ci_test \
  --test-enable --test-tags "/stock_barcodes" --stop-after-init
dropdb ot_ci_test
```

CI 中 `manifestoo check-licenses` 失败 → 检查 `__manifest__.py` 的 `license` 字段。
CI 中 `manifestoo check-dev-status --default-dev-status=Beta` 失败 → 检查 `development_status` 字段。
CI 中 `unreleased-deps` 失败 → `requirements.txt` 不允许 URL/相对路径，改为纯包名。

### 7. 常见测试失败与修复
| 现象 | 原因 | 修复 |
|---|---|---|
| `ModuleNotFoundError: python-barcode` | venv 未装 | `pip install python-barcode` |
| `pre_init_hook` 失败 | 库残留旧列 | `ALTER TABLE stock_move_line DROP COLUMN IF EXISTS barcode_scan_state;` 后重装 |
| 测试看不到夹具 | Odoo 19 REPEATABLE READ 隔离 | 用 `@tagged("post_install")` + `-i` 安装，勿跨连接读 |
| `bus.bus` 测试偶发失败 | longpolling 未就绪 | `--test-enable` 时禁用 bus 或加 `@tagged("standard")` |
| 资产加载失败 | 旧 manifest 引用了已删除文件 | 检查 `__manifest__.py` 的 `assets` 段，路径必须存在 |
| pylint `manifest-required-author` | author 字段格式错 | 必须包含 `Odoo Community Association (OCA)` |
| pylint `manifest-required-icon` | 缺 icon | OCA 19.0 不强制 icon，但部分 hook 仍检查；可加 `images` 或忽略 |
| `.pot` 提交冲突 | 多分支生成 | 本地勿手动改 `.pot`，由 CI OCB 矩阵推送 |

### 8. 测试日志位置
- 项目级：`/run/media/max/DATA1/projects/odoo-dev/19.0/logs/run_<dbname>.log`
- 默认 Odoo：`/run/media/max/DATA1/projects/odoo-dev/19.0/logs/odoo.log`
- 关注 `FAIL|ERROR|passed|failed` 关键字：
  ```bash
  grep -E "(FAIL|ERROR|passed|failed)" ../../logs/run_*.log | tail -20
  ```

## 示例

**用户问**："跑一下 stock_barcodes 的测试"

**回答**：
```bash
/run/media/max/DATA1/projects/odoo-dev/19.0/run_tests.sh --install stock_barcodes
```
该命令会创建临时库 `ot_19.0_<pid>`，安装模块并跑测试，结束自动 dropdb。日志在 `/run/media/max/DATA1/projects/odoo-dev/19.0/logs/run_ot_19.0_<pid>.log`。

**用户问**："pylint mandatory 报错怎么办"

**回答**：mandatory 不可降级。运行 `pre-commit run pylint_odoo --all-files -- --rcfile=.pylintrc-mandatory` 看具体规则，按提示修。常见项：`manifest-required-author`、`license-allowed`、`missing-readme`。
