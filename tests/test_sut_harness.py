"""被测运行脚手架(`tools/sut-harness/`)的离线守卫。

覆盖两层:
① **前置校验**(不需要 Docker / 被测仓)—— 路径不对、缺 .env 必须在碰 Docker 之前退出;
② **`docker run` 参数契约**(用 stub `docker`/`curl`,仍然不需要真 Docker)——
   保证「只读挂载、官方镜像、网络、env-file 覆盖、能力探针、被测自证」这些承诺
   不会在脚本漂移时静默失效。

真正起容器的那条路仍只能在真机上跑(README 已写明),不在离线套件里假装覆盖。

动机:脚手架此前散在 `/tmp`,**重启丢过两次**;固化后若无守卫,它会再次悄悄漂移
(这正是本仓「门禁需要门禁」的一贯做法,见 tests/test_hooks.py / test_coverage_gate.py)。
"""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "sut-harness"
RUN_SUT = HARNESS / "run_sut.sh"
README = HARNESS / "README.md"


def test_harness_files_exist():
    for f in (RUN_SUT, HARNESS / "sut_run.py", HARNESS / "sitecustomize.py", README):
        assert f.is_file(), f"脚手架缺文件: {f.name}"


def test_run_sut_is_executable_and_syntactically_valid():
    assert RUN_SUT.stat().st_mode & 0o111, "run_sut.sh 不可执行(chmod +x)"
    r = subprocess.run(["bash", "-n", str(RUN_SUT)], capture_output=True, text=True)
    assert r.returncode == 0, f"run_sut.sh 语法错误: {r.stderr}"


def _run_with_env(**over):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(Path.home())}
    env.update(over)
    return subprocess.run(["bash", str(RUN_SUT)], capture_output=True, text=True, env=env, timeout=60)


def test_rejects_missing_sut_repo_before_touching_docker(tmp_path):
    """路径不对必须**在碰 Docker 之前**就报错退出 —— 否则会在无关环境里乱起容器。"""
    r = _run_with_env(EVAL_SUT_REPO=str(tmp_path / "nope"))
    assert r.returncode == 1
    assert "被测仓路径不对" in r.stderr
    assert "Docker" not in r.stdout  # 未走到 Docker 分支


def test_rejects_sut_repo_without_env_file(tmp_path):
    """有 app/ 但缺 .env(容器要用它做 env-file)→ 同样前置失败。"""
    (tmp_path / "app").mkdir()
    r = _run_with_env(EVAL_SUT_REPO=str(tmp_path))
    assert r.returncode == 1
    assert ".env" in r.stderr


def test_script_takes_sut_path_from_env_not_hardcoded():
    """被测路径必须可注入 —— 本仓不得硬编码外部绝对路径(跨机器/换目录即失效)。"""
    text = RUN_SUT.read_text(encoding="utf-8")
    assert "EVAL_SUT_REPO" in text
    assert re.search(r'SUT_REPO="\$\{EVAL_SUT_REPO:-', text), "EVAL_SUT_REPO 未作为默认值来源"


def test_does_not_modify_the_sut_repo():
    """脚手架必须**只读挂载**被测仓 —— 这是「评测门不改被测」的结构保证。

    只读挂载点必须是 `/src`(再由容器内复制到可写 `/app`):
    直接只读挂到 `/app` 会挡住应用写 `.mem0/qdrant/.lock` 等运行时状态。
    """
    text = RUN_SUT.read_text(encoding="utf-8")
    assert re.search(r'-v "\$SUT_SRC:/src:ro"', text), "被测源码未以只读方式挂载到 /src"


# ── ② docker run 参数契约(stub,不需要真 Docker)──────────────────────────────

def _write_stub(bindir: Path, name: str, body: str):
    p = bindir / name
    p.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    p.chmod(0o755)


def _fake_repo(tmp_path: Path, *, layout: str = "app") -> Path:
    repo = tmp_path / "sut"
    (repo / layout).mkdir(parents=True)
    (repo / layout / "main.py").write_text("app = object()\n", encoding="utf-8")
    (repo / ".env").write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    return repo


def _run_with_stubs(tmp_path: Path, repo: Path, **over):
    """用 stub `docker`/`curl` 跑完整脚本,返回 (CompletedProcess, docker 调用记录, 自证文件内容)。"""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "docker-calls.txt"
    _write_stub(bindir, "docker", f"""printf '%s\\n' "$*" >> {record}
case "$1" in
  info|start|exec|rm|logs) exit 0 ;;
  run) echo fake-container-id; exit 0 ;;
  *) exit 0 ;;
esac
""")
    _write_stub(bindir, "curl", """
if printf '%s' "$*" | grep -q -- '-w'; then printf '200'; exit 0; fi
if printf '%s' "$*" | grep -q '/health'; then printf '{"status":"healthy"}'; exit 0; fi
printf '{"answer":"ok"}'
""")
    identity = tmp_path / "identity.env"
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "EVAL_SUT_REPO": str(repo),
        "EVAL_SUT_FASTAPI_API_KEY": "dummy",
        "EVAL_SUT_IDENTITY": str(identity),
    }
    env.update(over)
    r = subprocess.run(["bash", str(RUN_SUT)], capture_output=True, text=True, env=env, timeout=60)
    return r, (record.read_text(encoding="utf-8") if record.exists() else ""), (
        identity.read_text(encoding="utf-8") if identity.exists() else "")


def test_official_image_path_and_readonly_mount(tmp_path):
    """新版被测( `app/` )必须走官方镜像:源码**只读**挂到 /src,容器内复制到可写 /app。"""
    repo = _fake_repo(tmp_path, layout="app")
    r, calls, _ = _run_with_stubs(tmp_path, repo)
    assert r.returncode == 0, r.stdout + r.stderr
    run_calls = [c for c in calls.splitlines() if c.startswith("run ")]
    assert len(run_calls) == 1, f"应只 docker run 一次,实际: {calls}"
    run = run_calls[0]
    assert f"{repo}/app:/src:ro" in run, run
    assert "cp -a /src/. /app/" in run, "容器内未把只读源码复制到可写 /app"
    assert "uvicorn main:app" in run, "未以 uvicorn 启动当前源码"
    assert "fastapi-rag-agent:latest" in run, "未使用当前官方镜像"
    assert "--network fastapi-rag-agent_app-net" in run, "未使用当前官方网络"
    assert "-e DOCKER_ENV=true" in run
    assert "-e LLM_MODEL_FAST=deepseek-v4-flash" in run
    assert "-e LLM_MODEL_CHAT=deepseek-v4-flash" in run
    assert "/deps" not in run, "官方镜像不需要旧 /deps 卷"
    assert "pip install" not in run, "官方镜像不需要启动时补装依赖"


def test_prefers_app_over_api_when_both_exist(tmp_path):
    repo = _fake_repo(tmp_path, layout="app")
    (repo / "api").mkdir()
    r, calls, _ = _run_with_stubs(tmp_path, repo)
    assert r.returncode == 0, r.stdout + r.stderr
    run = next(c for c in calls.splitlines() if c.startswith("run "))
    assert f"{repo}/app:/src:ro" in run, "同时存在 app/ 与 api/ 时应优先 app/"


def test_db_and_session_limit_are_passed_through(tmp_path):
    """评测需要的两个覆盖必须能传进容器:隔离库 / 会话预算。"""
    repo = _fake_repo(tmp_path, layout="app")
    r, calls, _ = _run_with_stubs(
        tmp_path, repo,
        EVAL_SUT_DB="rag_eval_20261018",
        EVAL_SUT_SESSION_TOKEN_LIMIT="200000",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    run = next(c for c in calls.splitlines() if c.startswith("run "))
    assert "-e POSTGRES_DB=rag_eval_20261018" in run
    assert "-e SESSION_TOKEN_LIMIT=200000" in run


def test_capability_probe_and_identity_are_kept(tmp_path):
    """能力探针不能省;被测自证(commit/probe)必须落盘 —— DEC-016。"""
    repo = _fake_repo(tmp_path, layout="app")
    r, calls, identity = _run_with_stubs(tmp_path, repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "能力探针" in r.stdout
    assert "EVAL_SUT_PROBE=ok" in identity
    assert "EVAL_SUT_VERSION=" in identity


def test_readme_documents_retirement_condition_and_capability_probe():
    """README 必须写明**退出条件**与**能力探针的必要性** —— 否则这层会变成永久负债。"""
    text = README.read_text(encoding="utf-8")
    assert "退出条件" in text, "README 未写退出条件(本层定位是过渡/兜底)"
    assert "能力探针" in text, "README 未写能力探针"
    assert "不剥离行内" in text or "不剥离" in text, "README 未写 --env-file 不剥注释的坑"
