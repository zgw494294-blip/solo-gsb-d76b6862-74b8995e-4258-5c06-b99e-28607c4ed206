"""FastAPI 应用入口：POST /v1/evaluate、POST /v1/invert。"""
from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import EvalError
from .evaluator import convert_result, evaluate, value_from_unit
from .expression import iter_variables, parse_expression
from .models import EvalRequest, EvalResponse, InvertRequest, InvertResponse
from .solver import solve_target
from .units import ALLOWED_UNITS, parse_target

app = FastAPI(
    title="量纲公式求值 API",
    version="1.1.0",
    description="离线量纲公式求值：解析算术算式，按单位代数求值并换算到目标单位；"
    "支持按目标值在有限区间上反求单个变量。",
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@app.exception_handler(EvalError)
async def eval_error_handler(_: Request, exc: EvalError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": [{"type": exc.type, "loc": exc.loc, "msg": exc.msg}]},
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _known_env(variables: dict) -> dict:
    """由请求中的已知变量构造求值环境，并校验单位。"""
    env: dict = {}
    for name, var in variables.items():
        if var.unit not in ALLOWED_UNITS:
            raise EvalError.at_variable(
                "unknown_unit",
                name,
                "unit",
                f"变量 {name!r} 的单位 {var.unit!r} 不受支持，"
                f"可用单位：{', '.join(sorted(ALLOWED_UNITS))}",
            )
        env[name] = value_from_unit(var.value, var.unit)
    return env


def _remap_target_loc(exc: EvalError) -> EvalError:
    """把指向 target_unit 的定位改写为反求请求中的 target.unit。"""
    if exc.loc[:2] == ["body", "target_unit"]:
        return EvalError(exc.type, ["body", "target", "unit", *exc.loc[2:]], exc.msg)
    return exc


@app.post("/v1/evaluate", response_model=EvalResponse)
def evaluate_endpoint(req: EvalRequest) -> EvalResponse:
    ast = parse_expression(req.expression)
    env = _known_env(req.variables)
    result = evaluate(ast, env)

    target = parse_target(req.target_unit)
    value, dimension = convert_result(result, target)
    return EvalResponse(value=value, unit=target.canonical, dimension=dimension)


@app.post("/v1/invert", response_model=InvertResponse)
def invert_endpoint(req: InvertRequest) -> InvertResponse:
    unknown = req.unknown
    ast = parse_expression(req.expression)

    # 待求变量必须是合法标识符（与算式词法一致）
    if _IDENT_RE.fullmatch(unknown.name) is None:
        raise EvalError(
            "invalid_identifier",
            ["body", "unknown", "name"],
            f"待求变量名 {unknown.name!r} 不是合法标识符："
            "须以字母或下划线开头，仅含字母、数字与下划线",
        )
    # 不能与已知变量重名
    if unknown.name in req.variables:
        raise EvalError(
            "duplicate_variable",
            ["body", "unknown", "name"],
            f"待求变量 {unknown.name!r} 与已知变量重名",
        )
    # 待求变量须在算式中出现
    var_nodes = list(iter_variables(ast))
    if not any(node.name == unknown.name for node in var_nodes):
        first_pos = var_nodes[0].pos if var_nodes else 0
        raise EvalError.at_expression(
            "unknown_not_in_expression",
            first_pos,
            f"待求变量 {unknown.name!r} 没有出现在算式中；"
            f"算式中出现的变量：{', '.join(sorted({n.name for n in var_nodes})) or '无'}",
        )
    # 待求变量单位必须受支持
    if unknown.unit not in ALLOWED_UNITS:
        raise EvalError(
            "unknown_unit",
            ["body", "unknown", "unit"],
            f"待求变量 {unknown.name!r} 的单位 {unknown.unit!r} 不受支持，"
            f"可用单位：{', '.join(sorted(ALLOWED_UNITS))}",
        )
    # 区间必须严格递增
    low, high = unknown.bounds
    if not low < high:
        raise EvalError(
            "invalid_interval",
            ["body", "unknown", "bounds"],
            f"区间必须严格递增：[{low:g}, {high:g}] 不满足下限 < 上限",
        )

    env = _known_env(req.variables)

    try:
        target = parse_target(req.target.unit)
        value, actual = solve_target(
            ast,
            env,
            unknown.name,
            unknown.unit,
            (low, high),
            req.target.value,
            target,
        )
    except EvalError as exc:
        raise _remap_target_loc(exc)

    return InvertResponse(
        value=value,
        unit=unknown.unit,
        actual_value=actual,
        actual_unit=target.canonical,
    )
