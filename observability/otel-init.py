"""OpenTelemetry 最小初始化片段(观测左移 · 样例,按需改)。

依据:B `05-模块-全链路追踪与观测`(OTel 标准 + OpenInference span kind)。
用法:进程启动时调用 init_otel();埋点见下方示例。
依赖(装进 requirements):
    opentelemetry-sdk
    opentelemetry-exporter-otlp-proto-http
    opentelemetry-instrumentation-... (按框架:FastAPI/OpenAI/LangChain 等)

注意:
- 这是"最小可跑片段",不是生产配置;采样策略/多后端/缓冲需按部署扩展。
- 入出参脱敏在业务埋点处自行保证;此处只搭管道。
- 避免锁仓:走 OTLP,后端(Phoenix/Langfuse/Jaeger/…)可换,勿改埋点。
"""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# trace_id 需全链路透传,若用 W3C 则框架自动处理;自定义协议见 observability/trace_id-规范.md


def init_otel(service_name: str | None = None) -> None:
    """初始化全局 TracerProvider,导出到 OTLP 端点。

    端点默认取环境变量 OTEL_EXPORTER_OTLP_ENDPOINT(如 http://localhost:4318)。
    """
    resource = Resource.create(
        {SERVICE_NAME: service_name or os.getenv("OTEL_SERVICE_NAME", "<服务名>")}
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    # 说明:OTLP over HTTP /v1/traces;如需 gRPC 换 OTLPSpanExporter(otlp.proto.grpc)


def get_tracer(name: str):
    """拿到模块级 tracer,用于埋 span。"""
    return trace.get_tracer(name)


# ── 埋点示例(span 动作命名遵循 trace_id-规范,含脱敏摘要)───────────────────
def _example_instrument():
    tracer = get_tracer("memory")
    with tracer.start_as_current_span("memory.retrieve") as span:
        span.set_attribute("module", "memory")
        span.set_attribute("action", "retrieve")
        # 入参摘要(脱敏)
        span.set_attribute("input.summary", "query_len=24,top_k=5")
        # 结果状态
        span.set_attribute("output.hits", 3)
        span.set_attribute("status", "ok")
    # 出错路径:span.record_exception(e);span.set_attribute("status","error")
