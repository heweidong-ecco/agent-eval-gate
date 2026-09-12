"""E4 LLM-as-Judge(contracts/评测-judge.md;DEC-002 模型可配)。

- 直调任意 OpenAI 兼容端点 `/chat/completions`(纯标准库 urllib,零依赖、防锁仓);
- 出参要求结构化 JSON;非 JSON 重问一次仍失败 → verdict=flag(不静默给分);
- FakeJudge = 离线占位(按 expected 启发式判分),供 CI/自证不含真实模型时跑全链路;
- grade_ref = judge 与人工标签一致率(E7 校准用)。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from eval_gate.config import JudgeConfig, judge_config

VERDICTS = {"pass", "fail", "flag"}
# 截断重试时放大预算的**封顶**(DEC-006 A2):推理型模型的 reasoning 与 content 共用
# `max_tokens`,截断 ⇒ 重试必须给更大预算;封顶防一次截断把成本上限顶穿。
MAX_TOKENS_CEILING = 8192

# 重试提示语**按根因分流** —— 旧版只有一句"上次不是合法 JSON",对"被截断"是误导:
# 截断时模型根本没写坏 JSON,而是被长度上限切掉了尾巴,正确补救是"更短的输出 + 更大预算"。
_RETRY_HINT_JSON = "上次不是合法 JSON,请只输出 JSON,不要任何其它文字。"
_RETRY_HINT_TRUNCATED = ("上次输出被长度上限截断,请直接给结论、reasons 精简,"
                         "只输出 JSON,不要任何其它文字。")


def _parse_failure_reason(attempts: int, finish_reasons: list, content_lens: list) -> str:
    """解析失败的结论必须**自带一手证据**(DEC-006 A3)。

    否则"为什么解析不出来"只能靠再花一次 token 复现 —— 本会话就卡在这里
    (`docs/复盘/2026-09-12-门自身判分器预算缺陷.md` 错误 #2)。
    """
    last_finish = finish_reasons[-1] if finish_reasons else None
    last_len = content_lens[-1] if content_lens else 0
    why = ""
    if "length" in finish_reasons:
        why = " ⇒ 输出被 max_tokens 截断(reasoning 与 content 共用该上限)"
    return (f"E_JUDGE_PARSE: 多次未返回合法结构化 JSON"
            f"(尝试 {attempts} 次;末次 finish_reason={last_finish!r}、"
            f"content 长度 {last_len}{why})")


class JudgeError(Exception):
    """judge **调用**失败(网络/HTTP),带契约错误码 —— 与 E_JUDGE_PARSE(解析失败)区分。

    码取 `contracts/评测-judge.md` 错误码表。映射(该表无「judge 服务端不可用」码,
    故以 `E_JUDGE_TIMEOUT` 作不可用伞码):
    - 401/403 → `E_JUDGE_AUTH`
    - 400/404 → `E_JUDGE_MODEL_UNKNOWN`(端点不认该模型名)
    - 超时 / 不可达 / 其余 HTTP → `E_JUDGE_TIMEOUT`
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
REFUSAL_TOKENS = ("无法回答", "不能回答", "抱歉", "没有相关", "知识库中没有", "无法确定")


@dataclass
class JudgeVerdict:
    verdict: str = "flag"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict, "score": self.score,
            "reasons": self.reasons, "evidence_refs": self.evidence_refs,
            "labels": self.labels,
        }


def _openai_chat_http(cfg: JudgeConfig, messages: list[dict],
                      max_tokens: int | None = None) -> tuple[str, dict, str | None]:
    """OpenAI 兼容 chat completions 调用(纯标准库)。

    返回 `(content, usage, finish_reason)`;`usage` 取响应里的 token 用量,供 L1「成本(judge token)」
    与契约 `评测-judge.md:44`「记录字段(报告侧必存)」使用(缺失则为空 dict)。

    **`finish_reason` 必须回传**(DEC-006 A2):`'length'` 表示输出被 `max_tokens` 截断 ——
    这与"模型不守格式"是**两种不同的失败**,截断时重试必须换参数(旧实现用同样参数重试,
    对截断结构性无效)。

    `max_tokens` 显式传入则覆盖配置(截断重试时放大预算用)。
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "max_tokens": cfg.max_tokens if max_tokens is None else max_tokens,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise JudgeError("E_JUDGE_AUTH", f"judge 鉴权失败: HTTP {e.code}")
        if e.code in (400, 404):
            raise JudgeError("E_JUDGE_MODEL_UNKNOWN", f"端点不认模型 {cfg.model!r}: HTTP {e.code}")
        raise JudgeError("E_JUDGE_TIMEOUT", f"judge 不可用: HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JudgeError("E_JUDGE_TIMEOUT", f"judge 不可达/超时: {e}")
    choice = (data.get("choices") or [{}])[0]
    return ((choice.get("message") or {}).get("content"),
            (data.get("usage") or {}),
            choice.get("finish_reason"))


def _parse_verdict(text: str) -> JudgeVerdict | None:
    """把模型 content 解析成 JudgeVerdict;不合法返回 None。"""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    verdict = obj.get("verdict", "flag")
    if verdict not in VERDICTS:
        return None
    try:
        score = float(obj.get("score", 1.0 if verdict == "pass" else 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return JudgeVerdict(
        verdict=verdict,
        score=max(0.0, min(1.0, score)),
        reasons=[str(x) for x in (obj.get("reasons") or [])],
        evidence_refs=[str(x) for x in (obj.get("evidence_refs") or [])],
        labels=[str(x) for x in (obj.get("labels") or [])],
    )


def build_item(case_id: int, question: str, expected: dict, sut_answer: str,
               sut_sources: list[str] | None = None,
               deterministic: dict | None = None) -> dict:
    return {
        "case_id": case_id, "question": question, "expected": expected,
        "sut_answer": sut_answer or "",
        "sut_sources": list(sut_sources or []),
        "deterministic": dict(deterministic or {}),
    }


class Judge:
    """真实 judge:可配任意 OpenAI 兼容模型(默认读 EVAL_JUDGE_*)。

    记录 **judge 用量/成本**(`usage`)—— 契约 `评测-judge.md:44`「记录字段(报告侧必存)」
    与 L1 指标「成本(judge token)」。
    """

    def __init__(self, cfg: JudgeConfig | None = None, chat=None):
        self.cfg = cfg or judge_config()
        self._chat = chat or (lambda msgs, max_tokens=None:
                              _openai_chat_http(self.cfg, msgs, max_tokens))
        self.usage: dict[str, int] = {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            # DEC-006 A3:诊断计数 —— 随 `usage` 自动落进 run JSON。
            # `calls` 与用例数对不上时,差额就是**被重试掩盖的失败次数**(复盘 R4)。
            "retries": 0,          # 发生过几次"重试"(即第 2 次及以后的尝试)
            "parse_failures": 0,   # 有几次尝试的内容解析不出合法 JSON
            "truncated": 0,        # 有几次尝试 `finish_reason='length'`(输出被预算截断)
            "parse_flags": 0,      # 有几条用例最终因解析失败记 flag
        }
        # 最近一次 `grade()` 的逐次尝试轨迹(供 trace 记"这条为什么走得慢")。
        self.last_diagnostics: dict = {}

    def _record_usage(self, usage: dict | None) -> None:
        self.usage["calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                self.usage[k] += int((usage or {}).get(k) or 0)
            except (TypeError, ValueError):
                pass

    def _call_chat(self, msgs: list[dict],
                   max_tokens: int | None = None) -> tuple[str | None, str | None]:
        """调底层 chat,返回 `(content, finish_reason)`。

        注入桩可返回 str、`(content, usage)`、`(content, usage, finish_reason)`;
        仅当需要**放大预算**(截断重试)时才把 `max_tokens` 传给桩,以保持既有桩的兼容。
        """
        out = self._chat(msgs) if max_tokens is None else self._chat(msgs, max_tokens=max_tokens)
        if isinstance(out, tuple):
            content, usage, finish = (list(out) + [None, None])[:3]
            self._record_usage(usage)
            return content, finish
        return out, None

    def enabled(self) -> bool:
        return self.cfg.enabled()

    def label(self) -> str:
        return self.cfg.label()

    def _messages(self, item: dict) -> list[dict]:
        sys = (
            "你是严谨的 Agent 输出判分器。根据 question、expected(期望)与被测输出 sut_answer 判定。\n"
            "**expected 的语义(按契约 contracts/评测-evals-schema.md:30,必须严格遵守)**:\n"
            "- `answer_contains`:**含其一即符** —— 命中其中【任意一个】即视为该期望已满足,"
            "**不得要求全部命中**,也不得因未命中其余项而判 fail;\n"
            "- `answer_not_contains`:**禁现** —— 出现其中任意一个即判 fail;\n"
            "- `must_refuse`:为 true 时被测须拒答(输出了实质内容即判 fail)。\n"
            "- ⚠️ **拒答语境的边界(必须照此判,不要用常识替代)**:被测整句是**拒答**"
            "(如「无法回答」「资料未提及」「均不涉及 X」等)时,只要句中**出现了** `answer_contains` 里的任一候选词,\n"
            "  **该期望即算满足 ⇒ 判 pass**;**不得**因为「它没有真正回答所问」「命中出现在否定性语境里」\n"
            "  而改判 flag 或 fail。(「含其一即符」是**字面**规则;被测是否真正作答,不在本判据的裁量范围内。)\n"
            "  —— 该边界来自 2026-09-12 人工校准(DEC-009):首测 3 条分歧**全是**这个形状,而裁定口径是 pass。\n"
            "判分看**语义是否契合**,不要求措辞完全一致(同义/近义表述应视为命中);\n"
            "但**「是否真正作答」不改变字面命中的结论**(见上条边界)。\n"
            '只输出一个 JSON,不要任何其它文字:{"verdict":"pass|fail|flag","score":0..1,'
            '"reasons":["逐条依据，含对 expected 的命中/偏离"],"evidence_refs":[],"labels":[]}。'
            "flag 用于存疑需人工复核。"
        )
        user = json.dumps({
            "question": item.get("question"),
            "expected": item.get("expected"),
            "sut_answer": item.get("sut_answer"),
            "sut_sources": item.get("sut_sources", []),
            "deterministic": item.get("deterministic", {}),
        }, ensure_ascii=False)
        return [{"role": "system", "content": sys}, {"role": "user", "content": user}]

    def grade(self, item: dict) -> JudgeVerdict:
        attempts = 0
        finish_reasons: list[str | None] = []
        content_lens: list[int] = []
        budget: int | None = None          # None = 用配置值;截断后放大
        last_finish: str | None = None
        for attempt in range(1 + self.cfg.retries):
            msgs = self._messages(item)
            if attempt > 0:
                self.usage["retries"] += 1
                # 重试提示语必须说明**真实原因**:截断与"不守格式"的补救方向不同。
                msgs = msgs + [{"role": "user", "content":
                                _RETRY_HINT_TRUNCATED if last_finish == "length"
                                else _RETRY_HINT_JSON}]
            attempts += 1
            try:
                text, last_finish = self._call_chat(msgs, budget)
            except JudgeError as e:
                # 契约 评测-judge.md:41「超时:重试 1 次 → 仍超时抛 E_JUDGE_TIMEOUT」
                if e.code == "E_JUDGE_TIMEOUT" and attempt < self.cfg.retries:
                    continue
                raise
            finish_reasons.append(last_finish)
            content_lens.append(len(text or ""))
            if last_finish == "length":
                self.usage["truncated"] += 1
                # 截断 ⇒ 下次尝试给更大预算;不放大则重试**必然**再次被截断(DEC-006 A2)。
                budget = min((budget or self.cfg.max_tokens) * 2, MAX_TOKENS_CEILING)
            verdict = _parse_verdict(text)
            if verdict is not None:
                self._record_diagnostics(attempts, finish_reasons, content_lens)
                return verdict
            self.usage["parse_failures"] += 1
        self.usage["parse_flags"] += 1
        self._record_diagnostics(attempts, finish_reasons, content_lens)
        return JudgeVerdict(verdict="flag", score=0.0,
                            reasons=[_parse_failure_reason(attempts, finish_reasons, content_lens)])

    def _record_diagnostics(self, attempts: int, finish_reasons: list,
                            content_lens: list) -> None:
        self.last_diagnostics = {"attempts": attempts,
                                 "finish_reasons": list(finish_reasons),
                                 "content_lens": list(content_lens)}

    def effective_config(self) -> dict:
        """生效配置(进 run 产物,让"实际用的什么预算"看得见 —— DEC-006 A4)。"""
        return {"model": self.cfg.model, "base_url": self.cfg.base_url,
                "max_tokens": self.cfg.max_tokens, "retries": self.cfg.retries,
                "timeout_s": self.cfg.timeout_s}

    def grade_ref(self, refs: list[dict]) -> float | None:
        """judge 判定 vs 人工标签 一致率(refs 含 human:True/False)。"""
        if not refs:
            return None
        agree = 0
        for r in refs:
            v = self.grade(r).verdict == "pass"
            agree += 1 if v == bool(r.get("human")) else 0
        return agree / len(refs)


class FakeJudge(Judge):
    """离线占位 judge(自证/CI 无真实模型时用):按 expected 做简单启发判分。"""

    def __init__(self):
        super().__init__(cfg=JudgeConfig(), chat=lambda msgs: "{}")

    def enabled(self) -> bool:
        return False

    def effective_config(self) -> dict | None:
        """离线替身没有"生效预算"可言。

        不覆盖的话会从基类继承出一个 `model=None, max_tokens=4096` 的**假配置**,
        让产物看起来像真调过模型(与 `label()=='offline'` 的诚实口径冲突)。
        """
        return None

    def grade(self, item: dict) -> JudgeVerdict:
        exp = item.get("expected") or {}
        ans = item.get("sut_answer") or ""
        contains = exp.get("answer_contains") or []
        not_contains = exp.get("answer_not_contains") or []
        if exp.get("must_refuse"):
            refused = any(t in ans for t in REFUSAL_TOKENS)
            return JudgeVerdict("pass" if refused else "fail",
                                1.0 if refused else 0.0,
                                ["拒答合规" if refused else "应拒答却作答"])
        if not_contains:
            hit = [t for t in not_contains if t in ans]
            return JudgeVerdict("fail" if hit else "pass", 0.0 if hit else 1.0,
                                [f"命中禁现 {hit}"] if hit else ["未命中禁现词"])
        if contains:
            ok = any(t in ans for t in contains)
            return JudgeVerdict("pass" if ok else "fail", 1.0 if ok else 0.0,
                                ["命中期望要点"] if ok else [f"未命中 {contains}"])
        return JudgeVerdict("pass", 0.8, ["无明确期望,放行"])
