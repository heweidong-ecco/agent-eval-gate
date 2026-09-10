"""E1 评测集装载与校验(contracts/评测-evals-schema.md)。

纪律:坏配置/空评测集必须【零模型调用即失败】——load_evals 只做文件与结构校验,
不触碰任何被测/judge I/O。错误统一抛 EvalError(code, message)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SUTS = {"mini-rag-qa", "fastapi-rag"}  # = contracts/评测-evals-schema.md:26 的 sut 枚举
MODULES = {"rag", "task", "memory", "tool-mcp", "eval"}


class EvalError(Exception):
    """结构化的评测集错误。code 见 contracts/评测-evals-schema.md。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code


@dataclass
class Expected:
    answer_contains: list[str] = field(default_factory=list)
    answer_not_contains: list[str] = field(default_factory=list)
    must_refuse: bool = False
    ideal_tool_seq: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.answer_contains or self.answer_not_contains
                    or self.ideal_tool_seq or self.must_refuse)


@dataclass
class Checks:
    deterministic_only: bool = False


@dataclass
class Case:
    id: int
    sut: str
    module: str
    input: dict
    expected: Expected
    tags: list[str] = field(default_factory=list)
    checks: Checks = field(default_factory=Checks)
    source: str | None = None


@dataclass
class EvSet:
    version: int
    threshold_ref: str
    cases: list[Case]
    sut_default: str | None = None
    sample: dict | None = None
    judge_cfg: dict | None = None


def _invalid(msg: str) -> EvalError:
    return EvalError("E_SCHEMA_INVALID", msg)


def _parse_case(raw: dict, top: dict, seen_ids: set[int]) -> Case:
    try:
        cid = int(raw["id"])
    except (KeyError, TypeError, ValueError):
        raise _invalid(f"case 缺合法 int id: {raw!r}")
    if cid in seen_ids:
        raise EvalError("E_CASE_ID_DUP", f"case id={cid} 重复")
    seen_ids.add(cid)

    module = raw.get("module")
    if module not in MODULES:
        raise _invalid(f"case id={cid} 的 module={module!r} 非法(须 ∈ {sorted(MODULES)})")

    inp = raw.get("input")
    if not isinstance(inp, dict) or not isinstance(inp.get("question"), str) or not inp["question"].strip():
        raise _invalid(f"case id={cid} 缺 input.question(str)")

    exp_raw = raw.get("expected", {})
    if not isinstance(exp_raw, dict):
        raise _invalid(f"case id={cid} expected 须为对象,实为 {type(exp_raw).__name__}")
    expected = Expected(
        answer_contains=list(exp_raw.get("answer_contains") or []),
        answer_not_contains=list(exp_raw.get("answer_not_contains") or []),
        must_refuse=bool(exp_raw.get("must_refuse", False)),
        ideal_tool_seq=list(exp_raw.get("ideal_tool_seq") or []),
    )
    if any(not isinstance(x, str) for x in expected.answer_contains + expected.answer_not_contains):
        raise _invalid(f"case id={cid} expected 列表须为 str")

    checks_raw = raw.get("checks") or {}
    if not isinstance(checks_raw, dict):
        raise _invalid(f"case id={cid} checks 须为对象")
    checks = Checks(deterministic_only=bool(checks_raw.get("deterministic_only", False)))

    # 规则可判性:deterministic_only 必须有机器规则(红队不走 LLM-judge)
    if checks.deterministic_only and not (expected.must_refuse or expected.answer_not_contains):
        raise EvalError(
            "E_DETERMINISTIC_RULE_MISSING",
            f"case id={cid} 标记 deterministic_only,但 expected 缺机器规则(须 must_refuse 或 answer_not_contains)",
        )
    # 非 deterministic_only:expected 空 → 语义不可判,拒绝
    if not checks.deterministic_only and expected.empty():
        raise EvalError("E_EXPECTED_EMPTY", f"case id={cid} 非 deterministic_only 却 expected 为空")

    sut = raw.get("sut") or top.get("sut_default")
    if sut not in SUPPORTED_SUTS:
        raise EvalError("E_UNKNOWN_SUT", f"case id={cid} 的 sut={sut!r} 未注册(支持 {sorted(SUPPORTED_SUTS)})")

    source = raw.get("source")
    return Case(
        id=cid, sut=sut, module=module, tags=list(raw.get("tags") or []),
        input=inp, expected=expected, checks=checks,
        source=source if isinstance(source, str) else None,
    )


def load_evals(path: str | Path) -> EvSet:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise EvalError("E_SCHEMA_INVALID", f"评测集不可读/非 JSON: {p} — {e}")
    if not isinstance(data, dict):
        raise _invalid("评测集顶层须为对象")

    version = data.get("version")
    if not isinstance(version, int):
        raise _invalid("顶层 version 须为 int")
    threshold_ref = data.get("threshold_ref")
    if not isinstance(threshold_ref, str) or not threshold_ref.strip():
        raise EvalError("E_THRESHOLD_REF_MISSING", "顶层缺 threshold_ref(指阈值文件)")
    evals = data.get("evals")
    if not isinstance(evals, list) or len(evals) == 0:
        raise EvalError("E_NO_CASES", "顶层 evals 为空列表")

    sut_default = data.get("sut_default")
    if sut_default is not None and sut_default not in SUPPORTED_SUTS:
        raise EvalError("E_UNKNOWN_SUT", f"sut_default={sut_default!r} 未注册")

    seen: set[int] = set()
    cases = [_parse_case(raw, data, seen) for raw in evals]
    return EvSet(
        version=version, threshold_ref=threshold_ref, cases=cases,
        sut_default=sut_default, sample=data.get("sample"), judge_cfg=data.get("judge"),
    )
