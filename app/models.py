"""请求/响应模型。"""
from __future__ import annotations

import math

from pydantic import BaseModel, Field, field_validator


class Variable(BaseModel):
    value: float = Field(allow_inf_nan=False, description="有限数值（不接受 inf/NaN/布尔）")
    unit: str = Field(min_length=1, description="受支持的单位符号，见 README 单位表")

    @field_validator("value", mode="before")
    @classmethod
    def _reject_bool(cls, v):
        if isinstance(v, bool):
            raise ValueError("value 必须是有限数值，不能是布尔值")
        return v


class EvalRequest(BaseModel):
    expression: str = Field(
        min_length=1,
        description="算式：数字、变量、括号、一元正负与 + - * /",
        examples=["dist / time"],
    )
    variables: dict[str, Variable] = Field(
        default_factory=dict, description="变量名 -> {value, unit}"
    )
    target_unit: str = Field(
        min_length=1,
        description="目标单位：受支持单位组成的乘除式（可带整数幂）或 1",
        examples=["m/s"],
    )


class EvalResponse(BaseModel):
    value: float = Field(description="按目标单位换算后的数值")
    unit: str = Field(description="归一化后的目标单位")
    dimension: str = Field(description="结果量纲，如 [length] / [time]；无量纲为 dimensionless")


class UnknownVariable(BaseModel):
    name: str = Field(
        min_length=1,
        description="待求变量名：必须是合法标识符，在算式中至少出现一次，且不与 variables 中的已知变量重名",
        examples=["v"],
    )
    unit: str = Field(min_length=1, description="待求变量的单位（受支持的单个单位符号）")
    bounds: list[float] = Field(
        min_length=2,
        max_length=2,
        description="严格递增的有限数值区间 [下限, 上限]（待求变量在 unknown.unit 刻度下的取值范围）",
    )

    @field_validator("bounds", mode="before")
    @classmethod
    def _reject_bool_and_non_finite(cls, v):
        if isinstance(v, list) and len(v) == 2:
            for x in v:
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    raise ValueError("区间端点必须是有限数值，不能是布尔值")
                if not math.isfinite(float(x)):
                    raise ValueError("区间端点必须是有限数值（拒绝 inf/NaN）")
        return v


class InvertRequest(BaseModel):
    expression: str = Field(
        min_length=1,
        description="算式：数字、变量、括号、一元正负与 + - * /；待求变量可出现多次",
        examples=["dist / time"],
    )
    variables: dict[str, Variable] = Field(
        default_factory=dict, description="已知变量名 -> {value, unit}"
    )
    unknown: UnknownVariable = Field(description="待求变量的名称、单位与严格递增的有限数值区间")
    target: Variable = Field(description="期望结果 {value, unit}：有限目标值与目标单位")


class InvertResponse(BaseModel):
    value: float = Field(description="求得的待求变量数值（按 unknown.unit 刻度）")
    unit: str = Field(description="待求变量的单位（即请求中的 unknown.unit）")
    actual_value: float = Field(description="把待求值代回算式后，按 target.unit 换算的实际结果")
    actual_unit: str = Field(description="归一化后的目标单位（target.unit）")
