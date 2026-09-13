"""DEC-016 · run 产物补**被测侧自证字段**。

起因:查「轮间 2× 延迟不稳」时**查不出根因** —— 而查不动的原因是
**产物里 judge 侧记全了(model/config/usage)、被测侧一个字段都没有**。
⇒ 本次把 `DEC-006 A4` 对 judge 做的那件事,做到被测侧。
"""
import json
from pathlib import Path

from eval_gate.judge import FakeJudge
from eval_gate.report import write_run
from eval_gate.runner import evaluate
from eval_gate.schema import load_evals

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "eval" / "mini_rag_qa.evals.json"


def _run():
    return evaluate(load_evals(MINI), quality="faithful", judge=FakeJudge())


def test_sut_info_lists_endpoint_identity():
    """每个用到的 sut 都要能自证:适配器类名 + 端点 + mode。"""
    s = _run().sut_info
    assert set(s) == {"endpoints", "versions", "probe"}   # versions = per-sut 映射(契约 sut_versions)
    info = s["endpoints"]["mini-rag-qa"]
    assert info["adapter"] == "MiniRagQaAdapter"
    # 离线桩无 base_url ⇒ 记为 None(**不是省略** —— "没有"与"没记"要能分开)
    assert "base_url" in info and info["base_url"] is None


def test_env_supplies_version_and_probe(monkeypatch):
    """被测版本与能力探针结果**门不可能自己知道** ⇒ 由 sut-harness 经环境变量供给。"""
    monkeypatch.setenv("EVAL_SUT_VERSION", "f2dad78")
    monkeypatch.setenv("EVAL_SUT_PROBE", "ok")
    s = _run().sut_info
    assert s["versions"] == {"mini-rag-qa": "f2dad78"}
    assert s["probe"] == "ok"


def test_missing_env_is_null_not_omitted(monkeypatch):
    """⚠️ 缺省记 **null**,不是省略字段 —— "这轮没自证"本身是信息。"""
    monkeypatch.delenv("EVAL_SUT_VERSION", raising=False)
    monkeypatch.delenv("EVAL_SUT_PROBE", raising=False)
    s = _run().sut_info
    assert "versions" in s and s["versions"] == {"mini-rag-qa": None}
    assert "probe" in s and s["probe"] is None


def test_report_json_carries_sut_block(tmp_path):
    """**落盘产物**里必须有 —— 否则等于没记(查悬案时读的是产物)。"""
    r = _run()
    p = write_run(r, tmp_path, MINI, "offline")
    doc = json.loads(Path(p).read_text(encoding="utf-8"))
    assert "sut" in doc, "产物缺少 sut 块"
    assert doc["sut"]["endpoints"]["mini-rag-qa"]["adapter"] == "MiniRagQaAdapter"


def test_sut_identity_does_not_leak_secrets():
    """base_url 可以记(它是端点);**api_key 绝不能进产物**。"""
    s = _run().sut_info
    text = json.dumps(s, ensure_ascii=False)
    assert "api_key" not in text and "key" not in text.lower().replace("toolkit", "")


# ── 契约声明的 run 记录字段(评测-report.md:20-28)─────────────────
def test_run_record_carries_all_contract_declared_fields(tmp_path):
    """契约 `评测-report.md:20-28` 声明的字段必须**真的落盘**。

    ⚠️ 2026-09-13 实测:契约声明 11 个,**产物只有 4 个** ——
    `eval_version` / `evals_file_sha` / `sut_versions` / `threshold_rev` / `git_commit` / `started_at` 全缺。
    该缺口 `docs/部署.md:96` **2026-09-11 已登记**却一直没修;而 P4-1 的集成报告还写着"契约零漂移"。
    """
    r = _run()
    p = write_run(r, tmp_path, MINI, "offline")
    doc = json.loads(Path(p).read_text(encoding="utf-8"))
    for k in ("eval_version", "evals_file_sha", "threshold_rev", "git_commit",
              "started_at", "sut"):
        assert k in doc, f"产物缺契约字段:{k}"
    assert isinstance(doc["evals_file_sha"], str) and len(doc["evals_file_sha"]) >= 8
    assert doc["sut"]["versions"], "sut_versions 契约要求 per-sut 版本(缺省可为 null,但键要在)"


def test_sut_versions_maps_each_sut(monkeypatch):
    """`sut_versions` 按契约是 **per-sut 映射**;版本由 `EVAL_SUT_VERSION` 供给,缺省 null。"""
    monkeypatch.setenv("EVAL_SUT_VERSION", "f2dad78")
    s = _run().sut_info
    assert s["versions"] == {"mini-rag-qa": "f2dad78"}

    monkeypatch.delenv("EVAL_SUT_VERSION", raising=False)
    s2 = _run().sut_info
    assert s2["versions"] == {"mini-rag-qa": None}, "缺省必须是 null,不是省略"
