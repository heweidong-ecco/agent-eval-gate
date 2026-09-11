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
from pathlib import Path
from typing import Any, Callable

from eval_gate import mini_rag
from eval_gate.obs import clean_text, digest
from eval_gate.rules import REFUSAL_LEXICON
from eval_gate.schema import Case


def load_snapshot(path: str | Path) -> dict[str, dict]:
    """装载被测**快照**(question -> 行)。取法见 `总纲.md` D-5:「HTTP/快照/回放」。

    快照 = 被测真实产出的事后回放(如 `eval/snapshots/*.json`),用于被测服务不可用
    或检索结果不可复现时的离线真实数据评测(契约 `评测-sut-adapter.md:42`)。
    """
    p = Path(path)
    rows = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"快照须为数组: {p}")
    return {r["question"]: r for r in rows if isinstance(r, dict) and r.get("question")}


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
    """被测输出的归一化表示(评测门只认这个)。

    `__post_init__` 做**不可信输入归一**:被测(或被人投毒的中间层)可能返回
    含孤立代理对的文本(JSON 转义 `"\\ud800"` 即可送达),而下游的摘要/落盘
    都会 `str.encode("utf-8")` —— 不归一就会把整轮评测掀翻,且崩溃退出码 1
    在 CI 里恰好等于「质量阻断」,一个字符能伪装成一次质量问题。
    """

    answer: str
    refused: bool = False
    sources: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    raw: Any = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.answer = clean_text(self.answer)
        self.sources = [clean_text(s) for s in self.sources]

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


class SutAdapter:
    """被测适配器基类:run_case(case) -> SutOutput。"""

    id: str = "base"

    def run_case(self, case: Case) -> SutOutput:
        raise NotImplementedError


class SutAdapterError(Exception):
    """带错误分级的被测错误(供 E5 重试/熔断判定)。

    `status` = 被测 HTTP 状态码(非 HTTP 失败如超时/快照未覆盖时为 None);
    E5 靠它区分 `429`(限速重试)与其它 4xx(契约 `评测-sut-adapter.md:32` fail-fast)。
    """

    def __init__(self, code: SutErrorCode, message: str, status: int | None = None):
        super().__init__(f"[{code.name}] {message}")
        self.code = code
        self.status = status


class FastApiRagAdapter(SutAdapter):
    """真实被测 `01.FastAPI RAG Agent` 的 /rag/search 适配器。

    - 配置:EVAL_SUT_FASTAPI_BASE_URL(默认 http://localhost:8000)/ EVAL_SUT_FASTAPI_API_KEY;
    - post 可注入(离线测试);真实实现走 urllib(POST JSON);
    - **取法(D-5:HTTP/快照/回放)**:默认 HTTP;设 `EVAL_SUT_FASTAPI_SNAPSHOT=<快照文件>`
      则改走**快照回放**(被测服务不在时用,见 `load_snapshot`);
    - 错误映射:E_SUT_AUTH/QUOTA/4XX/5XX/BAD_RESPONSE(contracts/评测-sut-adapter.md)。
    """

    id = "fastapi-rag"

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 post: Callable | None = None, top_k: int = 3, mode: str = "accurate_norerank",
                 quality: str | None = None, snapshot: str | Path | None = None):
        # mode 取**被测 API 的默认值**(api_v1_rag.py:460)。开重排(accurate/full)需要被测侧
        # 本地 CrossEncoder 模型(`reranker.py:14` 的 sentence-transformers + BAAI/bge-reranker-v2-m3),
        # 评测门不引入该重型依赖;且默认口径更能代表被测的生产行为。见 D-10i。
        # quality = 「被测 prompt 改好/改坏」旋钮,只有自证用被测 mini-rag-qa 有;
        # 真实被测无此旋钮 → 接收并忽略(适配器对 E5 调度层保持同一签名)。
        self.base_url = (base_url or os.getenv("EVAL_SUT_FASTAPI_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("EVAL_SUT_FASTAPI_API_KEY", "")
        self.top_k = top_k
        self.mode = mode
        self._post = post or self._default_post
        snap = snapshot if snapshot is not None else os.getenv("EVAL_SUT_FASTAPI_SNAPSHOT")
        self._snapshot_path = Path(snap) if snap else None
        self._snapshot = load_snapshot(snap) if snap else None

    def _from_snapshot(self, case: Case) -> SutOutput:
        """快照回放:按问题取被测**当时真实回答**。

        快照未覆盖该问题时**记 fail 而非放行** —— 缺证据不放行,与契约 exit 3
        「不假装全绿」同一精神(理由里写明「快照未覆盖」,便于 R2b 剔除该口径)。
        """
        row = self._snapshot.get(case.input["question"])
        if row is None:
            raise SutAdapterError(
                SutErrorCode.E_SUT_BAD_RESPONSE,
                f"快照未覆盖该问题({self._snapshot_path}):缺证据不放行",
            )
        answer = (row.get("actual_answer") or "").strip()
        if not answer:
            raise SutAdapterError(SutErrorCode.E_SUT_BAD_RESPONSE, "快照该条无 actual_answer")
        docs = row.get("retrieved_docs") or []
        return SutOutput(
            answer=answer,
            refused=any(tok in answer for tok in REFUSAL_LEXICON),
            sources=[f"snapshot:doc{i}" for i in range(len(docs))],
            raw=row,
            meta={"sut": self.id, "source": "snapshot", "snapshot": str(self._snapshot_path)},
        )

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
        if self._snapshot is not None:
            return self._from_snapshot(case)
        url = f"{self.base_url}/api/v1/rag/search?mode={self.mode}"
        # 契约 contracts/评测-sut-adapter.md:39「header 鉴权(X-API-Key 或 JWT)」;
        # 被测把 Authorization: Bearer 一律按 JWT 验签,API Key 必须走 X-API-Key(R0 纠错)。
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
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
        # ⚠️ 纪律:异常消息**绝不**携带响应体原文 —— 它会经 E5 的错误日志与 span.error
        # 落进 stderr 与 *.trace.jsonl(违反 observability/日志-schema.md:1「长文本正文不入日志」
        # 与 需求基线.md:149 红线)。响应体只保留**摘要**;原文留在 SutOutput.raw / 报告(审计用)。
        if status in (401, 403):
            code = SutErrorCode.E_SUT_AUTH if status == 401 else SutErrorCode.E_SUT_QUOTA
            raise SutAdapterError(code, f"被测拒绝(HTTP {status});响应摘要 {digest(data)}", status=status)
        if status >= 500:
            raise SutAdapterError(SutErrorCode.E_SUT_5XX,
                                  f"被测 5xx(HTTP {status});响应摘要 {digest(data)}", status=status)
        raise SutAdapterError(SutErrorCode.E_SUT_4XX,
                              f"被测 4xx(HTTP {status});响应摘要 {digest(data)}", status=status)


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
