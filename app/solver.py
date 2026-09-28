"""目标值反求：在给定区间上对单一待求变量做二分求解。

规则：
- 先检查区间两端点；任一端点结果已在容差内即直接返回。
- 仅当两端点结果与目标值之差严格异号（端点不构成异号括区时报 422）时二分。
- 每次迭代先检查中点，再按符号保留异号的一半；最多迭代 100 次。
- 收敛容差：1e-8 * max(1, |目标值|)。
- 区间内出现的零除、量纲错误或非有限结果均直接报 422（不把间断点当作解），
  100 次后仍未收敛同样报 422。
"""
from __future__ import annotations

from .errors import EvalError
from .evaluator import convert_result, evaluate, value_from_unit
from .units import TargetUnit

MAX_ITERATIONS = 100
TOLERANCE_SCALE = 1e-8


def _midpoint(lo: float, hi: float) -> float:
    """(lo + hi) / 2，且在同号（均接近 float64 上界）时用相减形式避免溢出。"""
    if (lo < 0.0) == (hi < 0.0):
        return lo + (hi - lo) / 2.0
    return (lo + hi) / 2.0


def solve_target(
    ast,
    env: dict,
    unknown_name: str,
    unknown_unit: str,
    bounds: tuple[float, float],
    target_value: float,
    target: TargetUnit,
) -> tuple[float, float]:
    """二分反求待求变量，返回 (待求值, 按目标单位换算的实际结果)。

    ``env`` 为不含待求变量的已知变量环境；所有求值错误（带算式位置的
    EvalError：零除、量纲不兼容、非有限结果等）原样向上传播。
    """
    low, high = bounds
    tolerance = TOLERANCE_SCALE * max(1.0, abs(target_value))

    def run(x: float) -> float:
        env[unknown_name] = value_from_unit(x, unknown_unit)
        result = evaluate(ast, env)
        value, _ = convert_result(result, target)
        return value

    # 先检查端点
    f_low = run(low)
    if abs(f_low - target_value) <= tolerance:
        return low, f_low
    f_high = run(high)
    if abs(f_high - target_value) <= tolerance:
        return high, f_high

    d_low = f_low - target_value
    d_high = f_high - target_value
    # 乘积用于判号，分别比较两侧与 0 的关系（NaN 即 False），不直接相乘以避免溢出
    same_sign = (d_low < 0.0) == (d_high < 0.0)
    if same_sign:
        raise EvalError(
            "no_bracketing_interval",
            ["body", "unknown", "bounds"],
            f"区间端点 {low:g}、{high:g} 处的结果分别为 {f_low:g}、{f_high:g}，"
            f"与目标值 {target_value:g} 之差不构成异号括区，无法二分求解",
        )

    for _ in range(MAX_ITERATIONS):
        mid = _midpoint(low, high)
        f_mid = run(mid)
        if abs(f_mid - target_value) <= tolerance:
            return mid, f_mid
        if mid == low or mid == high:
            break  # 有限精度下区间已无法继续二分
        d_mid = f_mid - target_value
        if (d_mid < 0.0) == (d_low < 0.0):
            low, d_low = mid, d_mid
        else:
            high, d_high = mid, d_mid

    raise EvalError(
        "not_converged",
        ["body", "unknown", "bounds"],
        f"二分迭代 {MAX_ITERATIONS} 次后仍未收敛到容差 {tolerance:g} 以内",
    )
