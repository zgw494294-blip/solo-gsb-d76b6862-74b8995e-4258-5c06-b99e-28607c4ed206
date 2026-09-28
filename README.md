# 量纲公式求值 API

离线运行的量纲公式求值服务：接收一个算术算式、一组带单位的变量和一个目标单位，
按单位代数（dimensional algebra）求值并把结果换算到目标单位，返回数值与量纲；
也支持给出期望结果，在有限数值区间上对单个变量做目标值反求（二分法）。

技术栈：Python 3.11+ · FastAPI · Pint · Uvicorn。全程本地计算，不访问任何外部服务。

## 快速开始（一条命令）

```bash
docker compose up --build
```

服务启动后监听本地 **8000** 端口：

- 正向求值：`http://localhost:8000/v1/evaluate`
- 目标值反求：`http://localhost:8000/v1/invert`
- 交互式文档（Swagger UI）：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/healthz`

不使用 Docker 的本地运行方式：

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

## API

### `POST /v1/evaluate`

请求体：

```json
{
  "expression": "dist / time",
  "variables": {
    "dist": { "value": 36, "unit": "km" },
    "time": { "value": 2,  "unit": "h" }
  },
  "target_unit": "m/s"
}
```

| 字段 | 说明 |
| --- | --- |
| `expression` | 算式：只允许数字、变量、括号、一元正负号与 `+ - * /` |
| `variables` | 变量名 → `{value, unit}`；`value` 必须是有限数值（拒绝 inf/NaN/布尔） |
| `target_unit` | 目标单位：受支持单位组成的乘除式（可用括号与整数幂 `^`/`**`），或 `1` 表示无量纲 |

成功响应 `200`：

```json
{ "value": 5.0, "unit": "m/s", "dimension": "[length] / [time]" }
```

- `value`：按目标单位换算后的数值
- `unit`：归一化后的目标单位
- `dimension`：结果量纲（无量纲时为 `dimensionless`）

更多示例：

```bash
# 温度：10 °C 加上 18 Δ°F（=10 Δ°C），结果为 20 °C
curl -X POST http://localhost:8000/v1/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"expression": "t + d",
       "variables": {"t": {"value": 10, "unit": "degC"},
                     "d": {"value": 18, "unit": "delta_degF"}},
       "target_unit": "degC"}'
# => {"value": 20.0, "unit": "degC", "dimension": "[temperature]"}
```

### `POST /v1/invert`

目标值反求：给定算式、已知变量、一个待求变量（名称、单位、严格递增的有限
数值区间）以及期望结果（目标值与目标单位），用二分法求待求变量的取值。

- 待求变量必须在算式中出现（可出现多次），且不能与 `variables` 中的已知变量重名。
- 求解完全沿用正向求值的语法、单位换算与绝对温度规则。
- **先检查区间两端点**：任一端点结果已在容差内即直接返回；两端点结果与目标值
  之差**不构成异号括区**时返回 422（不猜测、不外推）。
- 构成括区后仅对该区间二分，**最多迭代 100 次**；遇到零除、量纲错误、非有限
  结果等间断/非法情形立即返回 422，**不把间断点当作解**。
- 收敛判据：`|实际结果 - 目标值| ≤ 1e-8 × max(1, |目标值|)`；100 次后仍不满足
  返回 422（有限精度下区间无法继续二分同样视为未收敛）。

请求体：

```json
{
  "expression": "dist / time",
  "variables": { "dist": { "value": 36, "unit": "km" } },
  "unknown": { "name": "time", "unit": "h", "bounds": [0.1, 10] },
  "target":  { "value": 5, "unit": "m/s" }
}
```

| 字段 | 说明 |
| --- | --- |
| `expression` | 同 `/v1/evaluate` 的算式 |
| `variables` | 已知变量名 → `{value, unit}`（同正向求值） |
| `unknown.name` | 待求变量名：合法标识符，须在算式中出现且不与已知变量重名 |
| `unknown.unit` | 待求变量的单位（单位表中的**单个**单位；`bounds` 是该刻度下的数值） |
| `unknown.bounds` | 严格递增的有限数值区间 `[下限, 上限]`（拒绝 inf/NaN/布尔/长度不为 2） |
| `target.value` | 期望结果的有限数值（拒绝 inf/NaN/布尔） |
| `target.unit` | 目标单位：规则同正向求值的 `target_unit`（可复合、可幂、可为 `1`） |

成功响应 `200`：

```json
{ "value": 2.000000007450581, "unit": "h",
  "actual_value": 4.999999981373548, "actual_unit": "m/s" }
```

- `value`：求得的待求变量数值（按 `unknown.unit` 刻度）
- `unit`：待求变量的单位（即 `unknown.unit`）
- `actual_value`：把待求值代回算式后按目标单位换算的实际结果（与 `target.value`
  的差不超过容差）
- `actual_unit`：归一化后的目标单位

可执行示例：

```bash
# 36 km 的路程，想要 5 m/s 的速度，反求所需时间（小时）：约 2 h
curl -X POST http://localhost:8000/v1/invert \
  -H 'Content-Type: application/json' \
  -d '{"expression": "dist / time",
       "variables": {"dist": {"value": 36, "unit": "km"}},
       "unknown": {"name": "time", "unit": "h", "bounds": [0.1, 10]},
       "target": {"value": 5, "unit": "m/s"}}'
# => {"value":2.0000000074...,"unit":"h","actual_value":4.9999999813...,"actual_unit":"m/s"}

# 反求绝对温度：多少 degC 等于 68 degF —— 20 degC（仿射换算）
curl -X POST http://localhost:8000/v1/invert \
  -H 'Content-Type: application/json' \
  -d '{"expression": "t",
       "unknown": {"name": "t", "unit": "degC", "bounds": [0, 40]},
       "target": {"value": 68, "unit": "degF"}}'
# => {"value":20.0,"unit":"degC","actual_value":68.0,"actual_unit":"degF"}

# 端点恰好命中：x + b 在 x=0 处已等于 1 m，直接返回端点
curl -X POST http://localhost:8000/v1/invert \
  -H 'Content-Type: application/json' \
  -d '{"expression": "x + b",
       "variables": {"b": {"value": 1, "unit": "m"}},
       "unknown": {"name": "x", "unit": "m", "bounds": [0, 10]},
       "target": {"value": 1, "unit": "m"}}'
# => {"value":0.0,"unit":"m","actual_value":1.0,"actual_unit":"m"}

# 端点不构成异号括区：x*x 在 [1 s, 2 s] 恒正，目标 -1 s^2 -> 422
curl -s -X POST http://localhost:8000/v1/invert \
  -H 'Content-Type: application/json' \
  -d '{"expression": "x * x",
       "unknown": {"name": "x", "unit": "s", "bounds": [1, 2]},
       "target": {"value": -1, "unit": "s^2"}}'
# => {"detail":[{"type":"no_bracketing_interval",
#                "loc":["body","unknown","bounds"], ...}]}

# 间断点不当作解：1/x 在 [-1 s, 1 s] 端点异号，但中点 x=0 是极点 -> 422
curl -s -X POST http://localhost:8000/v1/invert \
  -H 'Content-Type: application/json' \
  -d '{"expression": "1 / x",
       "unknown": {"name": "x", "unit": "s", "bounds": [-1, 1]},
       "target": {"value": 0, "unit": "1/s"}}'
# => {"detail":[{"type":"division_by_zero",
#                "loc":["body","expression",2],"msg":"位置 2：除数为零"}]}
```

## 支持的单位

| 类别 | 单位 |
| --- | --- |
| 长度 | `m`、`cm`、`km` |
| 时间 | `s`、`min`、`h` |
| 质量 | `kg`、`g` |
| 绝对温度 | `K`、`degC`、`degF` |
| 温差 | `delta_K`、`delta_degC`、`delta_degF` |

变量单位必须是上表中的单个单位；目标单位可以是这些单位经 `*`、`/`、括号
和整数幂组合成的式子（如 `kg*m/s^2`、`m^2`、`1/(s)`），或 `1`。

## 运算规则

- **加减**：先把两侧换算到相同量纲再合并；量纲不兼容报 422。
- **乘除**：组合两侧量纲；除数为零报 422。
- **绝对温度**（`K`/`degC`/`degF`）：
  - 可加、减温差，结果仍为绝对温度（如 `10 degC + 5 delta_K`）；
  - 两个绝对温度只允许相减，结果为温差（如 `10 degC - 50 degF → 0 delta_K`）；
  - 不得取负（`-t` 报错），不得参与乘除，两个绝对温度不得相加。
- **温差**：视为普通量纲量，可参与四则运算（如 `delta_K / s`）。
- 目标单位换算：绝对温度结果只能换算到 `K`/`degC`/`degF`；非绝对温度结果
  不能换算到绝对温度单位（防止把温差“洗”成绝对温度）。`K` 是无偏移单位，
  可出现在复合目标中（如 `K/s`）；`degC`/`degF` 只能单独作为目标单位。

## 错误格式

所有领域错误返回 `422`，`detail` 中的 `loc` 指向出错字段或算式位置
（算式位置为 0 起的字符偏移量）：

```json
{
  "detail": [
    {
      "type": "incompatible_units",
      "loc": ["body", "expression", 2],
      "msg": "位置 2：加减两侧量纲不兼容：meter 与 second"
    }
  ]
}
```

| `type` | 含义 | `loc` 示例 |
| --- | --- | --- |
| `syntax_error` | 非法算式（非法字符、隐式乘法、函数调用、括号不配对等） | `["body","expression",1]` |
| `invalid_number` | 算式中的数字不是有限值 | `["body","expression",0]` |
| `unknown_variable` | 算式引用了未定义的变量 | `["body","expression",4]` |
| `unknown_unit` | 变量或目标单位使用了不支持的单位 | `["body","variables","x","unit"]` |
| `incompatible_units` | 加减量纲不兼容、结果与目标单位不兼容 | `["body","expression",2]` 或 `["body","target_unit"]` |
| `absolute_temperature` | 违反绝对温度规则（相加、取负、参与乘除等） | `["body","expression",0]` |
| `division_by_zero` | 除数为零 | `["body","expression",2]` |
| `invalid_target_unit` | 目标单位式非法 | `["body","target_unit",3]` |
| `non_finite_result` | 求值结果溢出为非有限值 | `["body","expression"]` |

`/v1/invert` 额外的错误类型（同样返回 422）：

| `type` | 含义 | `loc` 示例 |
| --- | --- | --- |
| `invalid_identifier` | 待求变量名不是合法标识符 | `["body","unknown","name"]` |
| `duplicate_variable` | 待求变量与已知变量重名 | `["body","unknown","name"]` |
| `unknown_not_in_expression` | 待求变量没有在算式中出现 | `["body","expression",4]` |
| `invalid_interval` | 区间不是严格递增的两个端点 | `["body","unknown","bounds"]` |
| `no_bracketing_interval` | 两端点结果与目标值之差不构成异号括区 | `["body","unknown","bounds"]` |
| `not_converged` | 二分 100 次（或有限精度下区间无法继续二分）仍未进入容差 | `["body","unknown","bounds"]` |

反求过程中算式求值产生的错误（`division_by_zero`、`incompatible_units`、
`absolute_temperature`、`non_finite_result` 等）沿用正向求值的类型与定位；
目标单位相关错误的定位前缀为 `["body","target","unit", ...]`。端点或二分中点
处出现零除/量纲错误均直接返回该错误，不会把间断点当作解。

请求体本身不合法（缺字段、类型错误、非有限数值、`bounds` 长度不为 2 等）同样返回 422，
由 FastAPI/Pydantic 给出字段级定位。

## 测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 项目结构

```
app/
  main.py        FastAPI 应用与路由（POST /v1/evaluate、POST /v1/invert、GET /healthz）
  models.py      请求/响应模型（有限数值校验、区间长度校验）
  expression.py  算式词法/语法分析（递归下降，带位置的错误；AST 变量遍历）
  evaluator.py   量纲求值语义（温度规则、零除、目标换算）
  solver.py      目标值反求：端点检查 + 异号括区二分（最多 100 次，容差 1e-8）
  units.py       Pint 注册表、受支持单位、温度仿射换算、目标单位解析
  errors.py      可定位的领域错误（统一映射为 422）
tests/
  test_api.py          /v1/evaluate 端到端行为测试
  test_invert_api.py   /v1/invert 端到端行为测试
Dockerfile
docker-compose.yml
requirements.txt / requirements-dev.txt
```

实现说明：Pint 负责单位注册、量纲追踪与一般量的换算；绝对温度的仿射换算
（`K`/`degC`/`degF` 互转及与温差的加减）由 `app/units.py` 手工实现，以便对
违反温度规则的运算给出指向算式具体位置的 422 错误。`delta_K` 在 Pint 默认
注册表中不存在，启动时以 `delta_K = kelvin` 补充定义。
