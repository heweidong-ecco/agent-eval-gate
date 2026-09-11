"""最小启动器:只挂 RAG 路由(评测门实际用到的接口)。

不动被测仓库;避开 main.py 里的前端/成本看板等重型可选依赖。
"""
import sys
from fastapi import FastAPI
import uvicorn

sys.path.insert(0, "/app")
from api_v1_rag import router as rag_router  # noqa: E402

app = FastAPI(title="agent-eval-gate harness (RAG router only)")


@app.get("/health")
def health():
    return {"status": "healthy"}


app.include_router(rag_router)
uvicorn.run(app, host="0.0.0.0", port=8000)
