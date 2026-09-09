"""迷你 RAG-QA 被测(自带 · 自证评测门用,DEC-001)。

无外部服务/额度依赖。两种 quality 模拟"prompt 改好/改坏":
- faithful  : 只用检索上下文作答;检索不到 → 诚实拒答(知识外);
- hallucinate: 无视上下文、一律抛固定"想当然"答案(模拟劣化 prompt)。
检索 = 极简关键词命中(教学用,勿当真实检索引擎)。
"""
from __future__ import annotations

from dataclasses import dataclass

REFUSAL_ANSWER = "抱歉,知识库中没有相关内容,我无法回答。"
HALLUCINATED_ANSWER = "按我的理解,答案应是 GX-404,不会有错。"


@dataclass(frozen=True)
class Doc:
    id: str
    text: str
    keywords: tuple[str, ...]


DOCS: list[Doc] = [
    Doc("python", "Python 语言于 1991 年发布,现广泛用于 AI。", ("Python", "1991")),
    Doc("pgvector", "pgvector 是 PostgreSQL 数据库的向量扩展,支持 HNSW 索引。", ("pgvector", "PostgreSQL", "向量")),
    Doc("langgraph", "LangGraph 用图来表示 Agent 的状态流转。", ("LangGraph", "图", "状态")),
    Doc("qdrant", "Qdrant 是一个独立的开源向量数据库。", ("Qdrant",)),
]


def _is_refusal(text: str) -> bool:
    return any(tok in text for tok in ("抱歉", "没有相关", "无法回答", "知识库中没有"))


def retrieve(question: str) -> list[Doc]:
    """关键词命中检索(任意一个 keyword 在问句里即命中该文档)。"""
    return [d for d in DOCS if any(k in question for k in d.keywords)]


def answer(question: str, quality: str = "faithful") -> str:
    if quality not in ("faithful", "hallucinate"):
        raise ValueError(f"unknown quality={quality!r}")
    if quality == "hallucinate":
        return HALLUCINATED_ANSWER
    matched = retrieve(question)
    if not matched:
        return REFUSAL_ANSWER
    return "\n".join(d.text for d in matched)


def looks_like_refusal(text: str) -> bool:
    return _is_refusal(text)
