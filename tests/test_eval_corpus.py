"""评测语料的可复现守卫(`tools/export_eval_corpus.py` / `tools/seed_eval_corpus.py`)。

**为什么要有这一组**:
- live 回归的结论只有在**同一份语料**上才可重算;而语料正文**不进公开仓**
  (本仓是 Public;正文放 `Product-external/eval-corpus/`,仓内只放清单 + 哈希);
- 因此必须守住两件事:
  ① 仓内**不出现**语料正文(只有 manifest/README);
  ② 导出/导入工具**按哈希校验**,清单与文件不一致时**拒绝**导入(不是警告后继续)。
"""
import hashlib
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "tools" / "export_eval_corpus.py"
SEED = ROOT / "tools" / "seed_eval_corpus.py"
MANIFEST = ROOT / "eval" / "corpus" / "manifest.json"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_manifest_shape_and_no_content():
    d = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert d["rows"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", d["sha256"]), d["sha256"]
    assert sum(d["sources"].values()) == d["rows"]
    assert d["corpus"].endswith(".jsonl")
    # 清单里不得出现语料正文:只允许固定字段,且除 sources(计数)外不得有嵌套结构
    allowed = {"_doc", "corpus", "corpus_path", "corpus_path_note", "sha256",
               "rows", "bytes", "generated_from", "generator", "sources"}
    assert set(d) <= allowed, f"清单出现未预期字段: {set(d) - allowed}"
    assert all(isinstance(v, int) for v in d["sources"].values())
    assert not any(isinstance(v, (list, dict)) for k, v in d.items() if k != "sources")


def test_repo_does_not_track_corpus_content():
    # 含未跟踪文件:提交前也要能跑(CI 里已跟踪)。
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "eval/corpus"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    files = [f for f in out.stdout.splitlines() if f]
    assert files, "eval/corpus 下应有清单/说明"
    assert all(f.endswith(("manifest.json", "README.md")) for f in files), files


def _stub_docker(tmp_path: Path, rows: list[dict]) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    stub = bindir / "docker"
    stub.write_text(
        "#!/bin/bash\n"
        f"cat <<'EOF'\n{payload}\nEOF\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bindir


def test_export_writes_jsonl_and_manifest(tmp_path):
    rows = [{"content": "doc one", "source": "a"}, {"content": "doc two", "source": "b"}]
    bindir = _stub_docker(tmp_path, rows)
    out = tmp_path / "corpus.jsonl"
    man = tmp_path / "manifest.json"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(Path.home())}
    r = subprocess.run(
        [sys.executable, str(EXPORT), "--db", "x", "--out", str(out), "--manifest", str(man)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()] == rows
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["rows"] == 2
    assert m["sha256"] == _sha(out)
    assert m["sources"] == {"a": 1, "b": 1}


def _make_corpus(tmp_path: Path, rows: list[dict]) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "corpus": corpus.name,
        "sha256": _sha(corpus),
        "rows": len(rows),
        "sources": {},
    }), encoding="utf-8")
    return corpus, manifest


def test_seed_refuses_hash_mismatch(tmp_path):
    corpus, manifest = _make_corpus(tmp_path, [{"content": "x", "source": "s"}])
    d = json.loads(manifest.read_text(encoding="utf-8"))
    d["sha256"] = "0" * 64
    manifest.write_text(json.dumps(d), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SEED), "--corpus", str(corpus), "--manifest", str(manifest), "--dry-run"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 1
    assert "sha256" in (r.stdout + r.stderr).lower()


def test_seed_dry_run_reports_count(tmp_path):
    corpus, manifest = _make_corpus(tmp_path, [{"content": "x", "source": "s"},
                                               {"content": "y", "source": "s"}])
    r = subprocess.run(
        [sys.executable, str(SEED), "--corpus", str(corpus), "--manifest", str(manifest), "--dry-run"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2" in r.stdout


class _Handler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        type(self).calls.append({
            "path": self.path,
            "api_key": self.headers.get("X-API-Key"),
            "documents": body.get("documents", []),
        })
        out = json.dumps({"status": "inserted", "count": len(body.get("documents", []))}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def test_seed_posts_batches_with_auth_header(tmp_path):
    rows = [{"content": f"d{i}", "source": "s"} for i in range(3)]
    corpus, manifest = _make_corpus(tmp_path, rows)
    _Handler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        r = subprocess.run(
            [sys.executable, str(SEED), "--corpus", str(corpus), "--manifest", str(manifest),
             "--base-url", f"http://127.0.0.1:{port}", "--api-key", "k", "--batch-size", "2"],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        server.shutdown()
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(_Handler.calls) == 2, _Handler.calls
    assert [len(c["documents"]) for c in _Handler.calls] == [2, 1]
    assert all(c["path"] == "/api/v1/rag/insert_batch" for c in _Handler.calls)
    assert all(c["api_key"] == "k" for c in _Handler.calls)
