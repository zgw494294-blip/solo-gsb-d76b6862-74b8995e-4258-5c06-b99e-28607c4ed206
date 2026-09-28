"""POST /v1/invert（目标值反求）的行为测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def invert(expression, unknown, target, variables=None):
    return client.post(
        "/v1/invert",
        json={
            "expression": expression,
            "variables": variables or {},
            "unknown": unknown,
            "target": target,
        },
    )


def ok(expression, unknown, target, variables=None):
    resp = invert(expression, unknown, target, variables)
    assert resp.status_code == 200, resp.text
    return resp.json()


def err(expression, unknown, target, variables=None):
    resp = invert(expression, unknown, target, variables)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, list) and detail, resp.text
    return detail[0]


def within_tolerance(actual, target_value):
    return abs(actual - target_value) <= 1e-8 * max(1.0, abs(target_value))


# ---------------------------------------------------------------------------
# 基本反求：线性、带单位换算、多次出现、非线性
# ---------------------------------------------------------------------------

def test_linear_inversion():
    # 2*x + b = 7 m（b = 1 m） -> x = 3 m
    body = ok(
        "2 * x + b",
        {"name": "x", "unit": "m", "bounds": [-10.0, 10.0]},
        {"value": 7.0, "unit": "m"},
        {"b": {"value": 1, "unit": "m"}},
    )
    assert body["value"] == pytest.approx(3.0, abs=1e-7)
    assert body["unit"] == "m"
    assert body["actual_unit"] == "m"
    assert within_tolerance(body["actual_value"], 7.0)


def test_velocity_solve_time_with_unit_conversion():
    # dist=36 km，期望速度 5 m/s，反求时间（h）：2 h
    body = ok(
        "dist / time",
        {"name": "time", "unit": "h", "bounds": [0.1, 10.0]},
        {"value": 5.0, "unit": "m/s"},
        {"dist": {"value": 36, "unit": "km"}},
    )
    assert body["value"] == pytest.approx(2.0, abs=1e-8)
    assert body["unit"] == "h"
    assert body["actual_unit"] == "m/s"
    assert within_tolerance(body["actual_value"], 5.0)


def test_solve_distance_single_unknown_unit_vs_compound_target():
    # 待求量单位是单个单位 km，目标单位是复合单位 m/s：36 km / 2 h = 5 m/s
    body = ok(
        "dist / t",
        {"name": "dist", "unit": "km", "bounds": [1.0, 100.0]},
        {"value": 5.0, "unit": "m/s"},
        {"t": {"value": 2, "unit": "h"}},
    )
    assert body["value"] == pytest.approx(36.0, abs=1e-7)
    assert body["unit"] == "km"
    assert within_tolerance(body["actual_value"], 5.0)


def test_unknown_appears_multiple_times():
    # (x + x) / 2 = 3 m -> x = 3 m
    body = ok(
        "(x + x) / 2",
        {"name": "x", "unit": "m", "bounds": [0.0, 100.0]},
        {"value": 3.0, "unit": "m"},
    )
    assert body["value"] == pytest.approx(3.0, abs=1e-7)


def test_quadratic_inversion():
    # x*x = 2 m^2，x 取正根 sqrt(2)
    body = ok(
        "x * x",
        {"name": "x", "unit": "m", "bounds": [1.0, 2.0]},
        {"value": 2.0, "unit": "m^2"},
    )
    assert body["value"] == pytest.approx(2 ** 0.5, abs=1e-8)
    assert body["actual_unit"] == "m^2"
    assert within_tolerance(body["actual_value"], 2.0)


def test_endpoint_hit_low_bound():
    body = ok(
        "x + b",
        {"name": "x", "unit": "m", "bounds": [0.0, 10.0]},
        {"value": 1.0, "unit": "m"},
        {"b": {"value": 1, "unit": "m"}},
    )
    assert body["value"] == pytest.approx(0.0, abs=1e-12)
    assert within_tolerance(body["actual_value"], 1.0)


def test_endpoint_hit_high_bound():
    body = ok(
        "x + b",
        {"name": "x", "unit": "m", "bounds": [0.0, 10.0]},
        {"value": 11.0, "unit": "m"},
        {"b": {"value": 1, "unit": "m"}},
    )
    assert body["value"] == pytest.approx(10.0, abs=1e-12)


def test_negative_bounds_and_target():
    # x*x*x = -8 s^3 -> x = -2 s
    body = ok(
        "x * x * x",
        {"name": "x", "unit": "s", "bounds": [-3.0, -1.0]},
        {"value": -8.0, "unit": "s^3"},
    )
    assert body["value"] == pytest.approx(-2.0, abs=1e-8)


def test_large_target_uses_relative_tolerance():
    # 右端点直接命中；大目标值用相对容差 1e-8*|target|
    body = ok(
        "x",
        {"name": "x", "unit": "m", "bounds": [0.0, 1e12]},
        {"value": 1e12, "unit": "m"},
    )
    assert body["value"] == pytest.approx(1e12)
    assert abs(body["actual_value"] - 1e12) <= 1e-8 * 1e12


def test_response_echoes_units_and_actual_result():
    body = ok(
        "dist / time",
        {"name": "time", "unit": "h", "bounds": [0.01, 100.0]},
        {"value": 10.0, "unit": "m/s"},
        {"dist": {"value": 72, "unit": "km"}},
    )
    # 72 km / t = 10 m/s -> t = 2 h
    assert body["value"] == pytest.approx(2.0, abs=1e-8)
    assert body["unit"] == "h"
    assert body["actual_unit"] == "m/s"
    assert within_tolerance(body["actual_value"], 10.0)


# ---------------------------------------------------------------------------
# 温度：绝对温度作为待求变量（仿射换算）
# ---------------------------------------------------------------------------

def test_absolute_temperature_unknown():
    # t + 10 delta_K = 303.15 K -> t = 20 degC
    body = ok(
        "t + d",
        {"name": "t", "unit": "degC", "bounds": [-100.0, 100.0]},
        {"value": 303.15, "unit": "K"},
        {"d": {"value": 10, "unit": "delta_K"}},
    )
    assert body["value"] == pytest.approx(20.0, abs=2e-6)
    assert body["actual_unit"] == "K"


def test_absolute_temperature_unknown_affine_target():
    # 目标用 degF：t(degC) -> 68 degF，即 20 degC
    body = ok(
        "t",
        {"name": "t", "unit": "degC", "bounds": [0.0, 40.0]},
        {"value": 68.0, "unit": "degF"},
    )
    assert body["value"] == pytest.approx(20.0, abs=1e-7)


def test_temperature_difference_inversion():
    # t - 50 degF（=10 degC） = 5 delta_K -> t = 15 degC
    body = ok(
        "t - t0",
        {"name": "t", "unit": "degC", "bounds": [-50.0, 50.0]},
        {"value": 5.0, "unit": "delta_K"},
        {"t0": {"value": 50, "unit": "degF"}},
    )
    assert body["value"] == pytest.approx(15.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 422：括区、间断点、量纲、收敛
# ---------------------------------------------------------------------------

def test_endpoints_same_sign_rejected():
    e = err(
        "x * x",
        {"name": "x", "unit": "s", "bounds": [1.0, 2.0]},
        {"value": -1.0, "unit": "s^2"},
    )
    assert e["type"] == "no_bracketing_interval"
    assert e["loc"] == ["body", "unknown", "bounds"]


def test_target_outside_endpoint_range_rejected():
    # x + b 在 [0,10] m 上取值 [1,11] m，目标 100 m 不构成括区
    e = err(
        "x + b",
        {"name": "x", "unit": "m", "bounds": [0.0, 10.0]},
        {"value": 100.0, "unit": "m"},
        {"b": {"value": 1, "unit": "m"}},
    )
    assert e["type"] == "no_bracketing_interval"
    assert e["loc"] == ["body", "unknown", "bounds"]


def test_pole_inside_bracketing_interval_rejected():
    # 1/x 在 [-1 s, 1 s] 端点异号，目标 0：x=0 是极点，不得当作解
    e = err(
        "1 / x",
        {"name": "x", "unit": "s", "bounds": [-1.0, 1.0]},
        {"value": 0.0, "unit": "1/s"},
    )
    assert e["type"] == "division_by_zero"
    assert e["loc"][:2] == ["body", "expression"]


def test_division_by_zero_inside_interval_locates_expression():
    # 1/(x-c)，括区 [4,6] s、c=5 s，目标 0：中点 5 s 处分母为零
    e = err(
        "1 / (x - c)",
        {"name": "x", "unit": "s", "bounds": [4.0, 6.0]},
        {"value": 0.0, "unit": "1/s"},
        {"c": {"value": 5, "unit": "s"}},
    )
    assert e["type"] == "division_by_zero"
    assert e["loc"] == ["body", "expression", 2]  # '/' 位置


def test_dimension_mismatch_at_endpoint_points_to_target_unit():
    e = err(
        "x",
        {"name": "x", "unit": "m", "bounds": [0.0, 10.0]},
        {"value": 1.0, "unit": "s"},
    )
    assert e["type"] == "incompatible_units"
    assert e["loc"] == ["body", "target", "unit"]


def test_non_converged_when_float_spacing_exceeds_tolerance():
    # (x - c)/d：斜率 1/1e-9 = 1e9。float64 在 0.5 附近间距约 1.1e-16，
    # 输出侧相邻可表示间隔约 1.1e-7，大于容差 1e-8；目标 5.5e-8 永不可达。
    e = err(
        "(x - c) / d",
        {"name": "x", "unit": "s", "bounds": [0.0, 1.0]},
        {"value": 5.5e-8, "unit": "1"},
        {"c": {"value": 0.5, "unit": "s"}, "d": {"value": 1e-9, "unit": "s"}},
    )
    assert e["type"] == "not_converged"
    assert e["loc"] == ["body", "unknown", "bounds"]


def test_absolute_temperature_muldiv_in_interval_rejected():
    # 待求绝对温度参与乘除：首次端点求值即按温度规则报错
    e = err(
        "t * 2",
        {"name": "t", "unit": "degC", "bounds": [0.0, 10.0]},
        {"value": 1.0, "unit": "1"},
    )
    assert e["type"] == "absolute_temperature"
    assert e["loc"][:2] == ["body", "expression"]


# ---------------------------------------------------------------------------
# 422：请求语义校验
# ---------------------------------------------------------------------------

def test_unknown_not_in_expression_points_to_expression():
    e = err(
        "a + b",
        {"name": "z", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "m"},
        {"a": {"value": 2, "unit": "m"}, "b": {"value": 0, "unit": "m"}},
    )
    assert e["type"] == "unknown_not_in_expression"
    assert e["loc"][:2] == ["body", "expression"]


def test_unknown_not_in_expression_with_no_variables():
    e = err(
        "1 + 2",
        {"name": "z", "unit": "s", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "1"},
    )
    assert e["type"] == "unknown_not_in_expression"
    assert e["loc"] == ["body", "expression", 0]


def test_unknown_duplicates_known_variable():
    e = err(
        "x + b",
        {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "m"},
        {"x": {"value": 2, "unit": "m"}, "b": {"value": 1, "unit": "m"}},
    )
    assert e["type"] == "duplicate_variable"
    assert e["loc"] == ["body", "unknown", "name"]


def test_unknown_invalid_identifier():
    e = err(
        "x + b",
        {"name": "1a", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "m"},
        {"b": {"value": 1, "unit": "m"}},
    )
    assert e["type"] == "invalid_identifier"
    assert e["loc"] == ["body", "unknown", "name"]


def test_unknown_unit_unsupported():
    e = err(
        "x",
        {"name": "x", "unit": "mile", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "m"},
    )
    assert e["type"] == "unknown_unit"
    assert e["loc"] == ["body", "unknown", "unit"]


def test_known_variable_unit_unsupported_still_located():
    e = err(
        "x + a",
        {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 3.0, "unit": "m"},
        {"a": {"value": 1, "unit": "mile"}},
    )
    assert e["type"] == "unknown_unit"
    assert e["loc"] == ["body", "variables", "a", "unit"]


def test_bounds_must_be_strictly_increasing_equal():
    e = err(
        "x",
        {"name": "x", "unit": "m", "bounds": [1.0, 1.0]},
        {"value": 1.0, "unit": "m"},
    )
    assert e["type"] == "invalid_interval"
    assert e["loc"] == ["body", "unknown", "bounds"]


def test_bounds_must_be_strictly_increasing_decreasing():
    e = err(
        "x",
        {"name": "x", "unit": "m", "bounds": [2.0, 1.0]},
        {"value": 1.5, "unit": "m"},
    )
    assert e["type"] == "invalid_interval"
    assert e["loc"] == ["body", "unknown", "bounds"]


def test_syntax_error_in_expression_still_points_to_expression():
    e = err(
        "x *",
        {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 1.0, "unit": "m"},
    )
    assert e["type"] == "syntax_error"
    assert e["loc"][:2] == ["body", "expression"]


def test_target_unit_syntax_error_remapped_under_target_unit():
    e = err(
        "x",
        {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 1.0, "unit": "m/"},
    )
    assert e["type"] == "invalid_target_unit"
    assert e["loc"][:3] == ["body", "target", "unit"]


def test_unknown_target_unit_remapped_under_target_unit():
    e = err(
        "x",
        {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 1.0, "unit": "mile"},
    )
    assert e["type"] == "unknown_unit"
    assert e["loc"][:3] == ["body", "target", "unit"]


# ---------------------------------------------------------------------------
# 422：请求体结构 / 有限数值（Pydantic）
# ---------------------------------------------------------------------------

def test_missing_fields_are_422():
    assert client.post("/v1/invert", json={}).status_code == 422
    assert client.post(
        "/v1/invert",
        json={"expression": "x", "unknown": {"name": "x", "unit": "m"},
              "target": {"value": 1, "unit": "m"}},
    ).status_code == 422


def test_bounds_wrong_length_are_422():
    assert invert(
        "x", {"name": "x", "unit": "m", "bounds": [0.0]},
        {"value": 1.0, "unit": "m"},
    ).status_code == 422
    assert invert(
        "x", {"name": "x", "unit": "m", "bounds": [0.0, 1.0, 2.0]},
        {"value": 1.0, "unit": "m"},
    ).status_code == 422


def test_non_finite_bounds_are_422():
    for bad in ("Infinity", "-Infinity", "NaN"):
        resp = invert(
            "x", {"name": "x", "unit": "m", "bounds": [0.0, bad]},
            {"value": 1.0, "unit": "m"},
        )
        assert resp.status_code == 422, bad


def test_bool_bounds_are_422():
    resp = invert(
        "x", {"name": "x", "unit": "m", "bounds": [0.0, True]},
        {"value": 1.0, "unit": "m"},
    )
    assert resp.status_code == 422


def test_non_finite_target_value_is_422():
    assert invert(
        "x", {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": "nan", "unit": "m"},
    ).status_code == 422


def test_empty_expression_is_422():
    assert invert(
        "   ", {"name": "x", "unit": "m", "bounds": [0.0, 1.0]},
        {"value": 1.0, "unit": "m"},
    ).status_code == 422
