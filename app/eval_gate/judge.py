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


def _openai_chat_http(cfg: JudgeConfig, messages: list[dict]) -> tuple[str, dict]:
    """OpenAI 兼容 chat completions 调用(纯标准库)。

    返回 `(content, usage)`;`usage` 取响应里的 token 用量,供 L1「成本(judge token)」
    与契约 `评测-judge.md:44`「记录字段(报告侧必存)」使用(缺失则为空 dict)。
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "max_tokens": cfg.max_tokens,
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
    return data["choices"][0]["message"]["content"], (data.get("usage") or {})


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
        self._chat = chat or (lambda msgs: _openai_chat_http(self.cfg, msgs))
        self.usage: dict[str, int] = {"calls": 0, "prompt_tokens": 0,
                                      "completion_tokens": 0, "total_tokens": 0}

    def _record_usage(self, usage: dict | None) -> None:
        self.usage["calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                self.usage[k] += int((usage or {}).get(k) or 0)
            except (TypeError, ValueError):
                pass

    def _call_chat(self, msgs: list[dict]) -> str:
        """调底层 chat。返回 `(content, usage)` 元组则累计用量;注入桩返回 str 亦可。"""
        out = self._chat(msgs)
        if isinstance(out, tuple):
            content, usage = out
            self._record_usage(usage)
            return content
        return out

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
            "判分看**语义是否契合**,不要求措辞完全一致(同义/近义表述应视为命中)。\n"
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
        for attempt in range(1 + self.cfg.retries):
            msgs = self._messages(item)
            if attempt > 0:
                msgs = msgs + [{"role": "user", "content": "上次不是合法 JSON,请只输出 JSON,不要任何其它文字。"}]
            try:
                text = self._call_chat(msgs)
            except JudgeError as e:
                # 契约 评测-judge.md:41「超时:重试 1 次 → 仍超时抛 E_JUDGE_TIMEOUT」
                if e.code == "E_JUDGE_TIMEOUT" and attempt < self.cfg.retries:
                    continue
                raise
            verdict = _parse_verdict(text)
            if verdict is not None:
                return verdict
        return JudgeVerdict(verdict="flag", score=0.0, reasons=["E_JUDGE_PARSE: 多次未返回合法结构化 JSON"])

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
