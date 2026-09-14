"""R0 最小韧性加固 —— 契约已写明的失败语义全落地。

契约依据:
- `contracts/评测-report.md:46` exit 3 = 运行错误/熔断 degraded(如 E_SUT_QUOTA/aborted);
- `contracts/评测-sut-adapter.md:34` E_SUT_QUOTA → **整批 aborted**,run degraded(不假装全绿);
- `contracts/评测-judge.md:41` E_JUDGE_TIMEOUT(E5 处置)。

R0 前的缺陷:judge 抛异常会穿出 evaluate → CLI 三层无捕获 → 整个进程 traceback 崩溃。
本文件同时充当 R0 的验收证据 —— 含**离线故障注入**(judge 端点指向不可达地址)。
全程离线,不发真实网络、不需任何密钥。
"""
import io
import json

import pytest

from eval_gate.adapters import (REGISTRY, SutAdapter, SutAdapterError, SutErrorCode,
                                SutOutput, register_adapter)
from eval_gate.cli import main
from eval_gate.config import JudgeConfig
from eval_gate.judge import FakeJudge, Judge, JudgeError
from eval_gate.runner import _sut_call_with_retry, default_thresholds, evaluate
from eval_gate.schema import Case, Checks, EvSet, Expected
import eval_gate.runner as runner_mod

QUOTA_SUT = "r0-quota-stub"


class _QuotaAdapter(SutAdapter):
    """模拟被测配额耗尽(403 Free quota exhausted)。"""

    id = QUOTA_SUT

    def run_case(self, case):
        raise SutAdapterError(SutErrorCode.E_SUT_QUOTA, "Free quota exhausted")


register_adapter(QUOTA_SUT, lambda **kw: _QuotaAdapter())


class _BoomJudge:
    """judge 运行时故障(非解析失败):调用即抛。"""

    def enabled(self) -> bool:
        return True

    def label(self) -> str:
        return "boom@test"

    def grade(self, item):
        raise RuntimeError("judge 连接被重置")


class _AuthFailJudge(_BoomJudge):
    def grade(self, item):
        raise JudgeError("E_JUDGE_AUTH", "凭证无效(401)")


def _case(i: int, sut: str = "mini-rag-qa", question: str = "Python 哪一年发布?") -> Case:
    return Case(id=i, sut=sut, module="rag", tags=[], input={"question": question},
                expected=Expected(answer_contains=["1991"]), checks=Checks(), source=None)


def _evset(cases: list[Case]) -> EvSet:
    return EvSet(version=1, threshold_ref="eval/阈值.md", cases=cases)


# --- ① judge 异常不崩(该 case 记 fail + 错误码) -------------------------------

def test_judge_exception_does_not_crash_run():
    """R0 前:此处会抛 RuntimeError 穿出 evaluate(进程崩)。"""
    res = evaluate(_evset([_case(1)]), judge=_BoomJudge(),
                   thresholds=default_thresholds())
    assert res.cases[0]["verdict"] == "fail"
    assert any("judge" in r for r in res.cases[0]["reasons"])
    assert res.exit_code in (1, 2), "judge 故障不得产 exit 0(不许静默全绿)"


def test_judge_exception_keeps_other_cases_alive():
    """judge 单条故障不得中断整批(逐条独立)。"""
    res = evaluate(_evset([_case(1), _case(2)]), judge=_BoomJudge(),
                   thresholds=default_thresholds())
    assert len(res.cases) == 2
    assert all(c["verdict"] == "fail" for c in res.cases)


def test_judge_error_code_is_recorded():
    res = evaluate(_evset([_case(1)]), judge=_AuthFailJudge(),
                   thresholds=default_thresholds())
    assert any("E_JUDGE_AUTH" in r for r in res.cases[0]["reasons"])


def test_unreachable_judge_endpoint_does_not_crash_process():
    """离线故障注入:judge 指向不可达端点(连接被拒),进程不得崩。"""
    cfg = JudgeConfig(base_url="http://127.0.0.1:1", api_key="k", model="m", timeout_s=0.5)
    res = evaluate(_evset([_case(1)]), judge=Judge(cfg), thresholds=default_thresholds())
    assert res.cases[0]["verdict"] == "fail"
    assert any("E_JUDGE_" in r for r in res.cases[0]["reasons"])


# --- ② E_SUT_QUOTA → 整批 aborted → exit 3 ----------------------------------

def test_quota_aborts_batch_and_degrades():
    res = evaluate(_evset([_case(1, QUOTA_SUT), _case(2, QUOTA_SUT), _case(3, QUOTA_SUT)]),
                   judge=FakeJudge(), thresholds=default_thresholds())
    assert res.degraded is True
    assert res.exit_code == 3
    assert "E_SUT_QUOTA" in (res.degraded_reason or "")


def test_quota_skips_remaining_cases():
    res = evaluate(_evset([_case(1, QUOTA_SUT), _case(2, QUOTA_SUT)]),
                   judge=FakeJudge(), thresholds=default_thresholds())
    assert res.summary["skipped"] == 1, "后续 case 不应继续发请求(配额已耗尽)"


def test_quota_does_not_silently_pass():
    """契约原文:不假装全绿。"""
    res = evaluate(_evset([_case(1, QUOTA_SUT)]), judge=FakeJudge(),
                   thresholds=default_thresholds())
    assert res.exit_code != 0


# --- ③ 常规路径不被 R0 改变(回归) -------------------------------------------

def test_healthy_run_is_not_degraded():
    res = evaluate(_evset([_case(1)]), judge=FakeJudge(), thresholds=default_thresholds())
    assert res.degraded is False
    assert res.degraded_reason is None
    assert res.exit_code == 0
    assert res.summary["skipped"] == 0


# --- ④ R0 验收:CLI 级离线故障注入(端到端) -----------------------------------

# ---- E5 重试退避(契约 评测-sut-adapter.md:30-32)--------------------------

RETRY_SUT = "r1b-retry-stub"


class _FlakyAdapter(SutAdapter):
    """前 `fail_times` 次抛指定错误码,之后成功。"""

    id = RETRY_SUT

    def __init__(self, fail_times, code, status=None, counter=None, answer="ok"):
        self.fail_times, self.code, self.status = fail_times, code, status
        self.counter = counter if counter is not None else []
        self.answer = answer

    def run_case(self, case):
        self.counter.append(1)
        if len(self.counter) <= self.fail_times:
            raise SutAdapterError(self.code, "boom", status=self.status)
        return SutOutput(answer=self.answer)


def _flaky(monkeypatch, fail_times, code, status=None):
    counter = []
    monkeypatch.setitem(REGISTRY, RETRY_SUT,
                        lambda **_kw: _FlakyAdapter(fail_times, code, status, counter))
    monkeypatch.setattr(runner_mod, "SUT_BACKOFF_S", 0.0)          # 测试不等退避
    monkeypatch.setattr(runner_mod, "SUT_RATE_LIMIT_BACKOFF_S", 0.0)
    return counter


def _call(case):
    return _sut_call_with_retry(REGISTRY[RETRY_SUT](), case)


def test_sut_timeout_is_retried(monkeypatch):
    counter = _flaky(monkeypatch, fail_times=2, code=SutErrorCode.E_SUT_TIMEOUT)
    out = _call(_case(1, RETRY_SUT))
    assert out.answer == "ok"
    assert len(counter) == 3, "总尝试应为 1 + SUT_RETRIES(2)"


def test_sut_5xx_is_retried(monkeypatch):
    counter = _flaky(monkeypatch, fail_times=1, code=SutErrorCode.E_SUT_5XX, status=503)
    assert _call(_case(1, RETRY_SUT)).answer == "ok"
    assert len(counter) == 2


def test_sut_429_is_retried(monkeypatch):
    counter = _flaky(monkeypatch, fail_times=1, code=SutErrorCode.E_SUT_4XX, status=429)
    assert _call(_case(1, RETRY_SUT)).answer == "ok"
    assert len(counter) == 2


def test_sut_4xx_non_429_is_fail_fast(monkeypatch):
    """契约:非 429 的业务 4xx → 该 case fail-fast,**不重试**。"""
    counter = _flaky(monkeypatch, fail_times=99, code=SutErrorCode.E_SUT_4XX, status=400)
    with pytest.raises(SutAdapterError):
        _call(_case(1, RETRY_SUT))
    assert len(counter) == 1


def test_sut_quota_is_not_retried(monkeypatch):
    """配额耗尽 → 整批 aborted,重试没有意义。"""
    counter = _flaky(monkeypatch, fail_times=99, code=SutErrorCode.E_SUT_QUOTA, status=403)
    with pytest.raises(SutAdapterError):
        _call(_case(1, RETRY_SUT))
    assert len(counter) == 1


def test_retries_give_up_and_raise_original_error(monkeypatch):
    counter = _flaky(monkeypatch, fail_times=99, code=SutErrorCode.E_SUT_TIMEOUT)
    with pytest.raises(SutAdapterError) as e:
        _call(_case(1, RETRY_SUT))
    assert e.value.code is SutErrorCode.E_SUT_TIMEOUT
    assert len(counter) == 3, "用尽后原样上抛"


# ---- 重试**可见性**:让"这轮到底重试过没有"在跑完之后还查得到(2026-09-14)----
#
# 动机(「轮间 2× 延迟」悬案复核时发现的**记录缺口**):
#   重试**只**出现在 `tracer.log("warn","sut","retry", …)` —— 而 `Tracer.log()`
#   **只写 log_stream、不落盘**(`obs.py:244`),`*.trace.jsonl` **只有 span、没有日志行**。
#   ⇒ **一轮跑完,就再也查不出它重试过没有。**
#   ⇒ 后果很具体:`sut.call` 全部 `status=ok` **推不出"没重试"** ——
#      **重试之后成功的那条,同样是 `ok`**。而「每条都多吃一次退避重试」恰好是
#      「+1.88 s/条的加性常量」的形状 ⇒ 这一种解释**曾经无法被排除,原因纯粹是记录不够**。
#   修法照抄 **judge 侧早已有的先例**(`runner.py:244` 把 `attempts`/`finish_reasons` 记进 span):
#      把 `attempts` / 末次错误码 / HTTP 状态写进 **`sut.call` span**(那才是会落盘的地方)。

def _diag(ad):
    return getattr(ad, "last_diagnostics", None)


def test_retried_call_exposes_attempts(monkeypatch):
    """重试后成功 → 诊断留下 **attempts=2** + 末次错误码与 HTTP 状态。"""
    counter = _flaky(monkeypatch, fail_times=1, code=SutErrorCode.E_SUT_5XX, status=503)
    ad = REGISTRY[RETRY_SUT]()
    assert _sut_call_with_retry(ad, _case(1, RETRY_SUT)).answer == "ok"
    assert len(counter) == 2, "前置条件:确实重试过一次"
    d = _diag(ad)
    assert d is not None, "适配器上必须留下诊断(否则重试不可见)"
    assert d["attempts"] == 2
    assert d["last_error"] == "E_SUT_5XX"
    assert d["http_status"] == 503


def test_first_try_success_reports_one_attempt(monkeypatch):
    """**没重试也要有诊断**:`attempts=1` —— "空白"与"1 次"必须可区分。

    (只记"重试时"会退回同一个毛病:看不到 = 无法区分"没重试"与"没记录"。)
    """
    _flaky(monkeypatch, fail_times=0, code=SutErrorCode.E_SUT_5XX, status=503)
    ad = REGISTRY[RETRY_SUT]()
    _sut_call_with_retry(ad, _case(1, RETRY_SUT))
    d = _diag(ad)
    assert d is not None and d["attempts"] == 1
    assert d["last_error"] is None, "一次就成功 ⇒ 没有末次错误"


def test_failed_call_still_exposes_attempts(monkeypatch):
    """重试**用尽后抛错** → 诊断**仍要留下** —— 失败路径恰恰最需要它。"""
    _flaky(monkeypatch, fail_times=99, code=SutErrorCode.E_SUT_TIMEOUT)
    ad = REGISTRY[RETRY_SUT]()
    with pytest.raises(SutAdapterError):
        _sut_call_with_retry(ad, _case(1, RETRY_SUT))
    d = _diag(ad)
    assert d is not None, "抛错路径也必须留下诊断"
    assert d["attempts"] == 3, "总尝试 = 1 + SUT_RETRIES(2)"
    assert d["last_error"] == "E_SUT_TIMEOUT"


def test_attempts_reach_the_span_so_it_survives_the_run(monkeypatch):
    """**端到端**:attempts 必须落到 `sut.call` **span** 上 —— 那才是会落盘的地方。

    只写 stderr 等于没写(`Tracer.log` 不落盘、`trace.jsonl` 只有 span)。
    这条同时也回答悬案:「重试过的那条 ≠ 没重试的那条」在产物里**可分辨**。
    """
    from eval_gate.obs import Tracer
    _flaky(monkeypatch, fail_times=1, code=SutErrorCode.E_SUT_5XX, status=503)
    tr = Tracer(log_stream=io.StringIO())
    ev = EvSet(version=1, threshold_ref="eval/阈值.md",
               cases=[_case(1, RETRY_SUT), _case(2, RETRY_SUT)])
    evaluate(ev, judge=FakeJudge(), thresholds=default_thresholds(), tracer=tr)

    spans = {s.attributes.get("case_id"): s for s in tr.spans if s.name == "sut.call"}
    assert set(spans) == {1, 2}, "两条 case 都该有 sut.call span"
    assert spans[1].attributes.get("attempts") == 2, "重试过的那条必须记 attempts=2"
    assert spans[2].attributes.get("attempts") == 1, "没重试的记 1(空白与 1 必须可区分)"
    assert spans[1].status == "ok", "重试后成功 ⇒ status 仍是 ok(**正是它掩盖了重试**)"


def test_judge_timeout_is_retried_once():
    """契约 评测-judge.md:41:超时重试 1 次 → 仍超时抛 E_JUDGE_TIMEOUT。"""
    calls = []

    def chat(_msgs):
        calls.append(1)
        raise JudgeError("E_JUDGE_TIMEOUT", "超时")

    j = Judge(JudgeConfig(base_url="http://x", api_key="k", model="m"), chat=chat)
    with pytest.raises(JudgeError):
        j.grade({"case_id": 1, "question": "q", "expected": {}, "sut_answer": "a"})
    assert len(calls) == 2, "超时应重试 1 次(共 2 次尝试)"


def test_cli_fault_injection_unreachable_judge_and_sut(tmp_path, monkeypatch):
    """judge 端点与真实被测端点**均不可达** → 进程不崩、逐条记 fail、exit 语义正确。

    同时验证 `fastapi-rag` 可作为 sut 装载(契约 评测-evals-schema.md:26 的枚举)。
    """
    monkeypatch.setattr(runner_mod, "SUT_BACKOFF_S", 0.0)      # 测试不等退避
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "m")
    monkeypatch.setenv("EVAL_SUT_FASTAPI_BASE_URL", "http://127.0.0.1:1")

    ev = {
        "version": 1, "threshold_ref": "eval/阈值.md", "sut_default": "fastapi-rag",
        "evals": [
            {"id": 1, "module": "rag", "input": {"question": "q1"},
             "expected": {"answer_contains": ["x"]}},                      # 被测不可达
            {"id": 2, "module": "rag", "sut": "mini-rag-qa",
             "input": {"question": "Python 哪一年发布?"},
             "expected": {"answer_contains": ["1991"]}},                    # 被测正常,judge 不可达
        ],
    }
    p = tmp_path / "fault.evals.json"
    p.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")

    rc = main(["run", "--evals", str(p), "--report-dir", str(tmp_path / "runs")])

    assert rc == 1, "全部 case 失败 → l2 阻断;不得崩、不得 exit 0"
    doc = json.loads(next((tmp_path / "runs").glob("*.local.json")).read_text(encoding="utf-8"))
    assert doc["degraded"] is False, "被测/ judge 故障 ≠ 配额熔断,不得误标 degraded"
    assert doc["exit_code"] == 1
    assert [c["verdict"] for c in doc["cases"]] == ["fail", "fail"]
    assert any("E_JUDGE_" in r for r in doc["cases"][1]["reasons"]), "judge 故障须带契约错误码"


# ---- 独立评审(2026-09-11)发现问题的回归 ------------------------------------

def test_cli_early_failure_with_bad_report_dir_still_returns_3(tmp_path):
    """评审 Important:`finally` 里 trace 落盘失败曾**顶掉契约 exit code**。

    `--report-dir` 指向一个**已存在的文件**时,finally 的 write_trace 会因 mkdir 失败而抛错;
    若它抛出,`main()` 崩溃退出码为 **1** —— 而 1 在 CI 里恰好等于「block/阻断发布」,
    一个 IO/路径问题会被读成「质量不过关」。
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    rc = main(["run", "--evals", str(tmp_path / "nope.json"), "--offline",
               "--report-dir", str(blocker)])
    assert rc == 3, f"必须返回契约内的 exit 3(配置错误),实际 {rc}"


def test_report_dir_is_a_file_with_valid_evalset_returns_3_not_1(tmp_path, capsys):
    """`--report-dir` 指向**已存在的文件**、且评测集**正常** ⇒ 必须 exit 3,**不得 exit 1**。

    ⚠️ 2026-09-13 **故障演练**(`tools/fault_drill.sh`)实测暴露的真缺陷:
    既有的 `test_cli_early_failure_with_bad_report_dir_still_returns_3` 用
    「**坏评测集** + 坏目录」—— **早退的 exit 3 把这条路径盖住了**。
    真实场景(评测集正常、只是产物目录不可写)会一直跑到 `report.write`
    ⇒ `mkdir(exist_ok=True)` 对**文件**仍抛 `FileExistsError` ⇒ **未捕获**
    ⇒ 进程 exit **1** —— 而 1 在本项目 = 「被拦 / 阻断发布」,
    于是**一个 IO/路径问题被读成「质量不合格」**(正是那条测试 docstring 警告的误读)。

    ⚠️ 同一个 `finally` 里 **trace** 落盘失败**是**优雅处理的(`cli.py:170`)—— 不对称本身就是线索。
    """
    from pathlib import Path
    mini = Path(__file__).resolve().parents[1] / "eval" / "mini_rag_qa.evals.json"
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    rc = main(["run", "--evals", str(mini), "--mode", "good", "--offline",
               "--report-dir", str(blocker)])
    err = capsys.readouterr().err
    assert rc == 3, f"IO/配置错误必须是 exit 3,实际 {rc}(exit 1 会被读成质量不合格)"
    assert "Traceback" not in err, "不得把未捕获异常抛给用户"
