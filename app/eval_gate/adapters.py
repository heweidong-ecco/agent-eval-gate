"""E2 被测适配器(contracts/评测-sut-adapter.md)。

被测统一为「input → SutOutput」;真实被测(fastapi-rag 等)在后续增量注册
(需其服务在跑/密钥)。本轮实现自含的 mini-rag-qa,用于 U1 自证闭环。
"""
from __future__ import annotations

import enum
import json
import os
import time
import urllib.error
import urllib.request
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


class SutAdapterError(Exception):
    """带错误分级的被测错误(供 E5 重试/熔断判定)。"""

    def __init__(self, code: SutErrorCode, message: str):
        super().__init__(f"[{code.name}] {message}")
        self.code = code


class FastApiRagAdapter(SutAdapter):
    """真实被测 `01.FastAPI RAG Agent` 的 /rag/search 适配器。

    - 配置:EVAL_SUT_FASTAPI_BASE_URL(默认 http://localhost:8000)/ EVAL_SUT_FASTAPI_API_KEY;
    - post 可注入(离线测试);真实实现走 urllib(POST JSON);
    - 错误映射:E_SUT_AUTH/QUOTA/4XX/5XX/BAD_RESPONSE(contracts/评测-sut-adapter.md)。
    """

    id = "fastapi-rag"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 post: Callable | None = None, top_k: int = 3, mode: str = "accurate"):
        self.base_url = (base_url or os.getenv("EVAL_SUT_FASTAPI_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("EVAL_SUT_FASTAPI_API_KEY", "")
        self.top_k = top_k
        self.mode = mode
        self._post = post or self._default_post

    def _default_post(self, url: str, headers: dict, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read().decode("utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            return e.code, data
        except urllib.error.URLError as e:
            raise SutAdapterError(SutErrorCode.E_SUT_TIMEOUT, f"被测不可达: {e}")

    def run_case(self, case: Case) -> SutOutput:
        url = f"{self.base_url}/api/v1/rag/search?mode={self.mode}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "question": case.input["question"], "top_k": self.top_k,
            "generate_answer": True, "citations": True,
        }
        status, data = self._post(url, headers, payload)
        if status == 200:
            answer = data.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise SutAdapterError(SutErrorCode.E_SUT_BAD_RESPONSE, "响应无 answer 文本")
            sources = [s.get("id") for s in (data.get("sources") or []) if isinstance(s, dict) and s.get("id")]
            return SutOutput(answer=answer, sources=sources, raw=data,
                             meta={"sut": self.id, "http_status": status})
        if status in (401, 403):
            code = SutErrorCode.E_SUT_AUTH if status == 401 else SutErrorCode.E_SUT_QUOTA
            raise SutAdapterError(code, str(data.get("detail") or data))
        if status >= 500:
            raise SutAdapterError(SutErrorCode.E_SUT_5XX, f"被测 5xx: {status} {data}")
        raise SutAdapterError(SutErrorCode.E_SUT_4XX, f"被测 4xx: {status} {data}")


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
register_adapter(FastApiRagAdapter.id, FastApiRagAdapter)
