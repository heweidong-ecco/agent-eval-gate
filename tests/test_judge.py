"""E4 LLM-judge(contracts/评测-judge.md):结构化判分 + HTTP(本地 loopback,零外网)。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eval_gate.config import JudgeConfig
from eval_gate.judge import FakeJudge, Judge, JudgeVerdict

ITEM = {
    "case_id": 1,
    "question": "Python 哪一年发布?",
    "expected": {"answer_contains": ["1991"]},
    "sut_answer": "答案是 1991 年。",
    "sut_sources": [],
    "deterministic": {"passed": True},
}


def content_chat(contents):
    """按调用次序依次返回 content 的可注入 chat 桩。"""
    calls = []

    def chat(messages):
        calls.append(messages)
        c = contents[min(len(calls) - 1, len(contents) - 1)]
        if callable(c):
            return c(messages)
        return c

    chat.calls = calls
    return chat


def test_grade_parses_structured_verdict():
    chat = content_chat([json.dumps(
        {"verdict": "pass", "score": 0.9, "labels": ["faithful"],
         "reasons": ["命中 1991"], "evidence_refs": ["sources[0]"]})])
    j = Judge(JudgeConfig(), chat=chat)
    v = j.grade(ITEM)
    assert v.verdict == "pass" and v.score == 0.9 and v.reasons == ["命中 1991"]


def test_grade_flags_when_two_non_json_attempts():
    chat = content_chat(["当然可以啦", "还是不能"])  # 两次都非 JSON → flag
    j = Judge(JudgeConfig(), chat=chat)
    v = j.grade(ITEM)
    assert v.verdict == "flag"
    assert any("JSON" in r or "parse" in r.lower() for r in v.reasons)
    assert len(chat.calls) == 2  # 重问过一次


def test_grade_second_attempt_succeeds():
    chat = content_chat(["随机废话", json.dumps({"verdict": "fail", "score": 0.1, "reasons": ["不行"]})])
    j = Judge(JudgeConfig(), chat=chat)
    v = j.grade(ITEM)
    assert v.verdict == "fail" and v.score == 0.1


# ---- 本地 loopback HTTP:验证真实请求路径/鉴权头/响应解析 ----
def _serve_verdict_json(content, usage=None):
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            captured["path"] = self.path
            captured["auth"] = self.headers.get("Authorization")
            captured["body"] = body
            payload = {"choices": [{"message": {"content": content}}]}
            if usage is not None:
                payload["usage"] = usage
            resp = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, captured


def test_http_client_posts_to_chat_completions_with_auth():
    server, captured = _serve_verdict_json(json.dumps(
        {"verdict": "pass", "score": 0.95, "reasons": ["ok"], "evidence_refs": []}))
    try:
        port = server.server_address[1]
        cfg = JudgeConfig(base_url=f"http://127.0.0.1:{port}", api_key="sk-test", model="m")
        j = Judge(cfg)
        v = j.grade(ITEM)
        assert v.verdict == "pass" and v.score == 0.95
        assert captured["path"].endswith("/chat/completions")
        assert captured["auth"] == "Bearer sk-test"
        assert captured["body"]["model"] == "m"
        assert captured["body"]["max_tokens"] == cfg.max_tokens
    finally:
        server.shutdown()


def test_fake_judge_agrees_with_contains_heuristic():
    f = FakeJudge()
    good = dict(ITEM)
    v = f.grade(good)
    assert v.verdict == "pass"
    bad = dict(ITEM, sut_answer="答案是 GX-404。")
    assert f.grade(bad).verdict == "fail"


def test_grade_ref_returns_agreement_fraction():
    # 桩:只依据 sut_answer 是否含 1991(不碰 expected,避免误命中)
    def chat(msgs):
        payload = json.loads(msgs[-1]["content"])
        ok = "1991" in payload["sut_answer"]
        return json.dumps({"verdict": "pass" if ok else "fail",
                           "score": 1.0 if ok else 0.0, "reasons": ["ok"]})

    j = Judge(JudgeConfig(), chat=chat)
    refs = [
        {"case_id": 1, "question": "q1", "expected": {"answer_contains": ["1991"]},
         "sut_answer": "1991", "human": True},
        {"case_id": 2, "question": "q2", "expected": {"answer_contains": ["1991"]},
         "sut_answer": "别的", "human": True},  # judge=fail 而 human=true → 不一致
    ]
    assert j.grade_ref(refs) == 0.5


def test_judge_enabled_flag():
    j = Judge(JudgeConfig(), chat=lambda m: "x")
    assert j.enabled() is False  # base_url/key/model 全空 = 离线


# ---- judge 成本统计(契约 评测-judge.md:44 / L1「成本(judge token)」)----

def test_usage_accumulates_from_tuple_chat():
    def chat(_msgs):
        return json.dumps({"verdict": "pass", "score": 1.0, "reasons": ["ok"]}), \
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

    j = Judge(JudgeConfig(), chat=chat)
    j.grade(ITEM)
    j.grade(ITEM)
    # 成本口径(calls / prompt / completion / total)+ 诊断计数(DEC-006 A3)。
    assert {k: j.usage[k] for k in ("calls", "prompt_tokens", "completion_tokens",
                                    "total_tokens")} == {"calls": 2, "prompt_tokens": 200,
                                                         "completion_tokens": 40, "total_tokens": 240}
    assert (j.usage["retries"], j.usage["truncated"],
            j.usage["parse_failures"], j.usage["parse_flags"]) == (0, 0, 0, 0)


def test_usage_from_http_response():
    server, _ = _serve_verdict_json(
        json.dumps({"verdict": "pass", "score": 1.0, "reasons": ["ok"]}),
        usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
    try:
        cfg = JudgeConfig(base_url=f"http://127.0.0.1:{server.server_address[1]}",
                          api_key="sk-t", model="m")
        j = Judge(cfg)
        j.grade(ITEM)
        assert j.usage["total_tokens"] == 10 and j.usage["calls"] == 1
    finally:
        server.shutdown()


def test_usage_stays_zero_for_string_chat_stub():
    """既有注入桩只返回 str → 用量保持 0,不得报错(向后兼容)。"""
    j = Judge(JudgeConfig(), chat=lambda m: json.dumps({"verdict": "pass", "score": 1.0}))
    j.grade(ITEM)
    assert j.usage["calls"] == 0 and j.usage["total_tokens"] == 0
