"""E2 迷你 RAG-QA 被测(mini_rag):忠实/劣化两态 + 检索/拒答。"""
import pytest

from eval_gate.mini_rag import answer, DOCS, HALLUCINATED_ANSWER, normalize_text


def test_faithful_answer_hits_corpus_fact():
    a = answer("Python 哪一年发布?", quality="faithful")
    assert "1991" in a


def test_faithful_retrieval_returns_relevant_doc_text():
    a = answer("pgvector 支持什么数据库?", quality="faithful")
    assert "PostgreSQL" in a


def test_faithful_out_of_scope_refuses():
    a = answer("谁知道隔壁王老师家在几楼?", quality="faithful")
    assert any(tok in a for tok in ("抱歉", "没有", "无法", "知识库"))


def test_hallucinate_mode_ignores_corpus_and_answers():
    a = answer("Python 哪一年发布?", quality="hallucinate")
    assert a == HALLUCINATED_ANSWER  # 劣化态:无视上下文
    assert "1991" not in a
    assert not any(tok in a for tok in ("抱歉", "无法"))


def test_docs_are_nonempty_and_well_formed():
    assert len(DOCS) >= 3
    for d in DOCS:
        assert d.id and d.text and d.keywords


def test_bad_quality_rejected():
    with pytest.raises(ValueError):
        answer("q", quality="nonsense")


def test_normalize_text_lowercases_and_strips_whitespace():
    assert normalize_text("  Hello World  ") == "hello world"


def test_normalize_text_is_idempotent_and_preserves_inner_text():
    assert normalize_text(" PGVector ") == normalize_text(normalize_text(" PGVector "))
    assert normalize_text("A B") == "a b"
