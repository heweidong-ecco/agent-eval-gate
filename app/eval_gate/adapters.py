"""E2 被测适配器(contracts/评测-sut-adapter.md)。

被测统一为「input → SutOutput」;真实被测(fastapi-rag 等)在后续增量注册
(需其服务在跑/密钥)。本轮实现自含的 mini-rag-qa,用于 U1 自证闭环。
"""
from __future__ import annotations

import enum
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from eval_gate import mini_rag
from eval_gate.schema import Case


class SutErrorCode(enum.Enum):
    """被测错误分级(供 E5 重试/熔断判定)。"""

    E_SUT_TIMEOUT = "被测超时"
    E_SUT_5XX = "被测 5xx/过载"
    E_SUT_4XX = "被测 4xx/限流"
    E_SUT_AUTH = "鉴权失败"
    E_SUT_QUOTA = "配额耗尽"
    E_SUT_BAD_RESPONSE = "响应不可解析"


@dataclass
class SutOutput:
    """被测输出的归一化表示(评测门只认这个)。"""

    answer: str
    refused: bool = False
    sources: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    raw: Any = None
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


class SutAdapter:
    """被测适配器基类:run_case(case) -> SutOutput。"""

    id: str = "base"

    def run_case(self, case: Case) -> SutOutput:
        raise NotImplementedError


class MiniRagQaAdapter(SutAdapter):
    """自带迷你 RAG-QA 被测(包装 mini_rag);quality 模拟 prompt 好坏。"""

    id = "mini-rag-qa"

    def __init__(self, quality: str = "faithful"):
        self.quality = quality

    def run_case(self, case: Case) -> SutOutput:
        q = case.input["question"]
        t0 = time.time()
        answer_text = mini_rag.answer(q, quality=self.quality)
        return SutOutput(
            answer=answer_text,
            refused=mini_rag.looks_like_refusal(answer_text),
            sources=[d.id for d in mini_rag.retrieve(q)],
            meta={"quality": self.quality, "latency_ms": int((time.time() - t0) * 1000)},
        )


# 注册中心:id -> 工厂(可带被测配置,如 quality)
REGISTRY: dict[str, Callable[..., SutAdapter]] = {}


def register_adapter(name: str, factory: Callable[..., SutAdapter]) -> None:
    REGISTRY[name] = factory


def get_adapter(name: str, **kw) -> SutAdapter:
    if name not in REGISTRY:
        raise KeyError(f"被测适配器未注册: {name}(已注册 {sorted(REGISTRY)})")
    return REGISTRY[name](**kw)


def list_adapters() -> list[str]:
    return list(REGISTRY)


register_adapter(MiniRagQaAdapter.id, MiniRagQaAdapter)
