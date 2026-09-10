"""E9 观测与成本(R3 观测左移;落地 `observability/` 四份规范)。

规范对齐:
- **trace_id/span_id**:W3C `traceparent` 兼容(32/16 位十六进制,`secrets` 随机)
  —— `observability/trace_id-规范.md` §1;入口生成、全链路透传(§2)。
- **span 命名** `{module}.{action}`,kind 用 **OpenInference** 语义
  —— `observability/trace_id-规范.md` §3。
- **结构化日志**:JSON 一行一事,字段照 `observability/日志-schema.md`。
- **脱敏**:被测回答等长文本只留 `{len, sha8}`,**不记原文**(`需求基线.md:149`
  「日志禁记录原始敏感」);全文留在 E7 报告里——那是**审计留痕**,与日志职责分离。

不锁仓(规范「优先 OTel/语义约定,勿用私有 span 格式」):
落盘为 **OTLP-JSON 兼容形状**(公开编码;OpenInference kind 走
`openinference.span.kind` 属性,不用私有字段),设 `EVAL_OTLP_ENDPOINT` 即可直接
POST 给任意 OTLP 后端(Jaeger/Phoenix/…);**不引入 opentelemetry-sdk 依赖**——
与本仓「纯标准库、防锁仓」一致,`observability/otel-init.py` 作为可选接法保留。

CLI 适配说明(与规范的一处差异,显式记录):规范的「本地 stdout → 采集器」面向常驻
服务;本产品是 CLI,stdout 是**人读的结果**,故结构化日志走 **stderr**(`2>log.jsonl`
即可采集),Trace 走 `eval/runs/<run_id>.trace.jsonl`。
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_NAME = "eval-gate"

STATUS_OK, STATUS_ERROR, STATUS_DEGRADED = "ok", "error", "degraded"

# OpenInference span kind 属性名(公开语义约定,非私有格式)
KIND_ATTR = "openinference.span.kind"

# OTLP SpanKind 枚举(INTERNAL=1);OpenInference 语义走属性,不占用 OTLP kind
_OTLP_KIND_INTERNAL = 1
_OTLP_STATUS = {STATUS_OK: 1, STATUS_ERROR: 2, STATUS_DEGRADED: 1}


def new_trace_id() -> str:
    """W3C traceparent 兼容:32 位十六进制(16 字节随机)。"""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """16 位十六进制(8 字节随机)。"""
    return secrets.token_hex(8)


def span_name(kind: str, ident) -> str:
    """拼 span 名:`{kind}/{ident}`(如 `sut.call/abc`)—— 同一动作下按对象区分。

    `kind` 沿用 `{module}.{action}`(规范 §3),故 `Span.module/action` 仍可从
    前缀取出;ident 只作后缀,不参与 `{module}.{action}` 语义(视图里按模块归位不受影响)。
    """
    return f"{kind}/{ident}"


def digest(text) -> dict:
    """脱敏摘要:只留长度与 sha256 前 8 位 —— 日志里**永不**出现原文。

    接受任意类型(非 str 先 JSON 序列化),便于给**响应体**之类结构做摘要:
    异常消息里只放 `digest(body)`,不放 body 本身(见 KD 记录:错误路径曾泄漏被测原文)。
    """
    if isinstance(text, str):
        s = text
    elif text is None:
        s = ""
    else:
        s = json.dumps(text, ensure_ascii=False, default=str)
    return {"len": len(s), "sha8": hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]}


def short_trace_id(trace_id) -> str:
    """trace_id 的短形式(前 8 位),供人读的紧凑视图使用。

    非字符串、或不足 8 位时返回空串 `""` —— 调用方(视图/报告)可能拿到 `None`
    或畸形 id,这里**不抛异常**,免得一个坏 id 打断整棵树/整行日志的渲染。
    仅用于显示;对外发/关联仍用完整 trace_id(规范 `trace_id-规范.md` §1)。
    """
    if isinstance(trace_id, str) and len(trace_id) >= 8:
        return trace_id[:8]
    return ""


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time_ns() % 1_000_000_000) // 1_000_000:03d}Z"


@dataclass
class Span:
    """一条 span(字段照 `trace_id-规范.md` §4「每条 span 必带」)。"""

    trace_id: str
    span_id: str
    name: str
    kind: str
    parent_span_id: str | None = None
    start_ns: int = 0
    duration_ms: float = 0.0
    status: str = STATUS_OK
    attributes: dict = field(default_factory=dict)
    error: dict | None = None

    @property
    def module(self) -> str:
        return self.name.split(".", 1)[0]

    @property
    def action(self) -> str:
        return self.name.split(".", 1)[1] if "." in self.name else ""

    def as_dict(self) -> dict:
        d = {
            "trace_id": self.trace_id, "span_id": self.span_id,
            "parent_span_id": self.parent_span_id, "name": self.name, "kind": self.kind,
            "start_time_ms": round(self.start_ns / 1e6, 3),
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status, "attributes": self.attributes,
        }
        if self.error:
            d["error"] = self.error
        return d

    def to_otlp(self) -> dict:
        """OTLP-JSON 形状的一条 span(可被任意 OTLP 后端摄取)。"""
        attrs = [{"key": KIND_ATTR, "value": {"stringValue": self.kind}}]
        attrs += [{"key": k, "value": {"stringValue": str(v)}} for k, v in self.attributes.items()]
        return {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            **({"parentSpanId": self.parent_span_id} if self.parent_span_id else {}),
            "name": self.name,
            "kind": _OTLP_KIND_INTERNAL,
            "startTimeUnixNano": str(self.start_ns),
            "endTimeUnixNano": str(self.start_ns + int(self.duration_ms * 1e6)),
            "attributes": attrs,
            "status": {"code": _OTLP_STATUS.get(self.status, 1)},
        }


class Tracer:
    """一次 run 的观测器:收集 span + 输出结构化日志。`enabled=False` 时全部空转。"""

    def __init__(self, trace_id: str | None = None, enabled: bool = True, log_stream=None):
        self.trace_id = trace_id or new_trace_id()
        self.enabled = enabled
        self._spans: list[Span] = []
        self._stack: list[str] = []
        self._log_stream = log_stream if log_stream is not None else sys.stderr

    @property
    def spans(self) -> list[Span]:
        return list(self._spans)

    @contextmanager
    def span(self, name: str, kind: str = "CHAIN", **attrs):
        """`with tr.span("sut.call", kind="AGENT", case_id=1) as sp:` —— 支持嵌套。"""
        if not self.enabled:
            yield None
            return
        sp = Span(trace_id=self.trace_id, span_id=new_span_id(), name=name, kind=kind,
                  parent_span_id=self._stack[-1] if self._stack else None,
                  start_ns=time.time_ns(), attributes=dict(attrs))
        self._spans.append(sp)
        self._stack.append(sp.span_id)
        t0 = time.perf_counter()
        try:
            yield sp
        except Exception as e:
            sp.status = STATUS_ERROR
            sp.error = {"code": type(e).__name__, "msg": str(e)[:200]}
            raise
        finally:
            sp.duration_ms = (time.perf_counter() - t0) * 1000
            self._stack.pop()

    def log(self, level: str, module: str, action: str, *, input=None, output=None,
            duration_ms: float | None = None, status: str = STATUS_OK,
            tags: dict | None = None, error: dict | None = None,
            span_id: str | None = None) -> None:
        """结构化日志(JSON 一行一事,字段照 `日志-schema.md`)。

        `span_id` 默认取当前 span;span 已退出时由调用方显式传入(如 run 级汇总日志
        属于根 span)——保证 `trace_id + span_id` 齐全、链路可重建(规范 §规则3)。
        """
        if not self.enabled:
            return
        rec: dict = {
            "timestamp": _iso_now(), "level": level, "module": module, "action": action,
            "trace_id": self.trace_id,
            "span_id": span_id or (self._stack[-1] if self._stack else None),
            "status": status, "tags": tags or {},
        }
        if input is not None:
            rec["input"] = input
        if output is not None:
            rec["output"] = output
        if duration_ms is not None:
            rec["duration_ms"] = round(duration_ms, 3)
        if error:
            rec["error"] = error
        self._log_stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._log_stream.flush()

    def otlp_document(self) -> dict:
        """整批 span 转 OTLP-JSON(可直接 POST 到 `/v1/traces`)。"""
        return {
            "resourceSpans": [{
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": SERVICE_NAME}}]},
                "scopeSpans": [{
                    "scope": {"name": SERVICE_NAME},
                    "spans": [s.to_otlp() for s in self._spans],
                }],
            }],
        }

    def write_trace(self, path: str | Path) -> Path:
        """落盘为 JSONL(一行一 span)。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for s in self._spans:
                f.write(json.dumps(s.as_dict(), ensure_ascii=False) + "\n")
        return p

    def export_otlp(self, endpoint: str | None = None) -> bool:
        """设了 `EVAL_OTLP_ENDPOINT` 才外发;失败**不阻塞主流程**(`trace_id-规范.md` §7)。"""
        url = endpoint or os.getenv("EVAL_OTLP_ENDPOINT")
        if not url or not self.enabled or not self._spans:
            return False
        body = json.dumps(self.otlp_document()).encode("utf-8")
        req = urllib.request.Request(url.rstrip("/") + "/v1/traces", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False


def render_tree(spans: list[Span], trace_id: str | None = None) -> str:
    """把 span 列表渲染成文本 **Trace 视图**(树形,按 parent 归位)。"""
    if not spans:
        return "(无 span)"
    by_parent: dict[str | None, list[Span]] = {}
    for s in spans:
        by_parent.setdefault(s.parent_span_id, []).append(s)
    for lst in by_parent.values():
        lst.sort(key=lambda s: s.start_ns)

    lines: list[str] = []
    if trace_id:
        lines.append(f"trace {trace_id}")

    def walk(parent: str | None, depth: int, prefix: str) -> None:
        kids = by_parent.get(parent, [])
        for i, s in enumerate(kids):
            last = i == len(kids) - 1
            branch = "└─ " if last else "├─ "
            mark = {"ok": "✓", "error": "✗", "degraded": "⚠"}.get(s.status, "·")
            note = f"  [{s.error['code']}: {s.error['msg'][:40]}]" if s.error else ""
            lines.append(f"{prefix}{branch}{s.name:<22} {s.kind:<8} {s.duration_ms:>9.1f}ms {mark}{note}")
            walk(s.span_id, depth + 1, prefix + ("   " if last else "│  "))

    walk(None, 0, "")
    return "\n".join(lines)


def read_trace(path: str | Path) -> list[Span]:
    """读回 JSONL trace(供 `eval-gate trace` 视图)。"""
    spans = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        spans.append(Span(
            trace_id=d["trace_id"], span_id=d["span_id"], name=d["name"], kind=d.get("kind", ""),
            parent_span_id=d.get("parent_span_id"), start_ns=int(d.get("start_time_ms", 0) * 1e6),
            duration_ms=d.get("duration_ms", 0.0), status=d.get("status", STATUS_OK),
            attributes=d.get("attributes") or {}, error=d.get("error"),
        ))
    return spans
