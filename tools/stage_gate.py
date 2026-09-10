#!/usr/bin/env python3
"""stage_gate —— 阶段硬门 + 检查点(治"长任务中间全白费")。

缘起(2026-09-11,业务方批准;来自对另一套 harness 的调研):
  那套 harness **零件齐全但从未接线** —— 它有 `state_tracker.py`(只写状态、不校验迁移)
  和 `check-gates.sh`(**一次性检查全部产出物**,而且不在任何链路里)。
  结果就是业务方指出的那个缺陷:**门禁只压在"最后一次提交",长任务中途断了/做错了 =
  前面全白费,且没有任何门触发过**。

本工具把"阶段门"做成**真状态机**:
  · 每个阶段有 **evidence(产出物)** —— 必须真实存在且非空;
  · **迁移前必须校验**:所有前置阶段都 passed,且它们的 evidence **现在依然在**;
  · **不满足就拒绝进入下一阶段**(exit 1);
  · `resume` 告诉你"从最后一个 passed 阶段继续" → 中断后可续跑,不必重来。

状态文件:`docs/state/<req>.json`(**入库** —— 这样换台机器也能续跑)。

用法:
    stage_gate.py init   --req <id> --config <stages.json>
    stage_gate.py enter  --req <id> --stage <name>     # 校验前置 → 进入该阶段(in_progress)
    stage_gate.py pass   --req <id>                    # 校验本阶段 evidence 存在 → 标记 passed
    stage_gate.py status --req <id>
    stage_gate.py resume --req <id>                    # 从哪继续

config 形状:
    {"stages": [{"name": "a", "evidence": ["path/to/artifact.md"]}, ...]}

退出码:0 成功;1 门禁未过;2 用法/配置错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("STAGE_GATE_ROOT") or Path(__file__).resolve().parents[1])
STATE_DIR = ROOT / "docs" / "state"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _state_path(req: str) -> Path:
    return STATE_DIR / f"{req}.json"


def _load(req: str) -> dict:
    p = _state_path(req)
    if not p.is_file():
        print(f"::error::状态文件不存在: {p}(先跑 init)")
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def _save(req: str, st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = _now()
    _state_path(req).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage_cfg(st: dict, name: str) -> dict | None:
    for s in st["stages"]:
        if s["name"] == name:
            return s
    return None


def _missing_evidence(stage: dict) -> list[str]:
    """产出物必须**存在且非空** —— 光"建了个空文件"不算交付。"""
    miss = []
    for rel in stage.get("evidence", []):
        p = ROOT / rel
        if not p.is_file() or p.stat().st_size == 0:
            miss.append(rel)
    return miss


def _passed(st: dict, name: str) -> bool:
    for h in st["history"]:
        if h["stage"] == name and h["status"] == "passed":
            return True
    return False


# ── 命令 ────────────────────────────────────────────────────────────────────

def cmd_init(a) -> int:
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    if not cfg.get("stages"):
        print("::error::config 里没有 stages")
        return 2
    st = {"req": a.req, "stages": cfg["stages"], "current": None, "history": [],
          "created_at": _now()}
    _save(a.req, st)
    print(f"✅ 已初始化 {a.req}:{len(st['stages'])} 个阶段 → {_state_path(a.req)}")
    return 0


def cmd_enter(a) -> int:
    st = _load(a.req)
    names = [s["name"] for s in st["stages"]]
    if a.stage not in names:
        print(f"::error::未知阶段 {a.stage!r};可选 {names}")
        return 2
    idx = names.index(a.stage)

    # 【核心】前置校验:所有更早的阶段必须 passed,且其 evidence **现在依然在**
    bad: list[str] = []
    for prev in names[:idx]:
        if not _passed(st, prev):
            bad.append(f"阶段 {prev} 未通过")
            continue
        miss = _missing_evidence(_stage_cfg(st, prev))
        if miss:
            bad.append(f"阶段 {prev} 的产出物缺失/为空: {miss}")

    if bad:
        print(f"::error::不能进入阶段 {a.stage} —— 前置门禁未过:")
        for b in bad:
            print(f"::error::  - {b}")
        print("::error::(阶段门必须在前一阶段【产出物真实存在】之后才放行;"
              "这正是『中间全白费』的第一个闸)")
        return 1

    st["current"] = a.stage
    st["history"].append({"stage": a.stage, "status": "in_progress", "at": _now()})
    _save(a.req, st)
    print(f"✅ 已进入阶段 {a.stage}(前置 {idx} 个阶段均已通过)")
    return 0


def cmd_pass(a) -> int:
    st = _load(a.req)
    if not st.get("current"):
        print("::error::还没有进入任何阶段(先 enter)")
        return 2
    cur = _stage_cfg(st, st["current"])
    miss = _missing_evidence(cur)
    if miss:
        print(f"::error::阶段 {st['current']} 的产出物缺失/为空: {miss}")
        print("::error::产出物不存在 = 这一阶段没真正完成 → 不算通过")
        return 1
    for h in reversed(st["history"]):
        if h["stage"] == st["current"] and h["status"] == "in_progress":
            h["status"] = "passed"
            h["passed_at"] = _now()
            break
    _save(a.req, st)
    print(f"✅ 阶段 {st['current']} 已通过(产出物齐备)")
    return 0


def cmd_status(a) -> int:
    st = _load(a.req)
    print(f"  req: {a.req} | current: {st.get('current')}")
    for s in st["stages"]:
        status = "-"
        for h in st["history"]:
            if h["stage"] == s["name"]:
                status = h["status"]
        mark = {"passed": "✅", "in_progress": "▶", "-": "⬜"}.get(status, "?")
        miss = _missing_evidence(s)
        note = f"  (产出物缺: {miss})" if miss else ""
        print(f"  {mark} {s['name']:<24} {status}{note}")
    return 0


def cmd_resume(a) -> int:
    """断点续跑:从**第一个"未通过 或 产出物已缺失"的阶段**继续。

    ⚠️ 必须**顺序走到第一个断点就停**,而不是取"最高的已通过阶段" ——
    否则某阶段的产出物事后被删/被改坏时,会**跳过它继续往前**(假装已完成)。
    这是本工具的第一版真 bug,由 `tests/test_stage_gate.py::test_removing_evidence_rolls_resume_back` 抓出。
    """
    st = _load(a.req)
    names = [s["name"] for s in st["stages"]]
    nxt_idx = len(names)
    for i, n in enumerate(names):
        if not (_passed(st, n) and not _missing_evidence(_stage_cfg(st, n))):
            nxt_idx = i
            break
    if nxt_idx >= len(names):
        print(f"✅ {a.req}:所有阶段已通过且产出物齐备,无待续")
        return 0
    nxt = names[nxt_idx]
    done = names[nxt_idx - 1] if nxt_idx > 0 else "(无)"
    print(f"▶ {a.req}:从阶段 {nxt} 继续(最后有效通过的阶段:{done})")
    print(f"  下一步:stage_gate.py enter --req {a.req} --stage {nxt}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stage_gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init");   p.add_argument("--req", required=True); p.add_argument("--config", required=True); p.set_defaults(f=cmd_init)
    p = sub.add_parser("enter");  p.add_argument("--req", required=True); p.add_argument("--stage", required=True);  p.set_defaults(f=cmd_enter)
    p = sub.add_parser("pass");   p.add_argument("--req", required=True);                                             p.set_defaults(f=cmd_pass)
    p = sub.add_parser("status"); p.add_argument("--req", required=True);                                             p.set_defaults(f=cmd_status)
    p = sub.add_parser("resume"); p.add_argument("--req", required=True);                                             p.set_defaults(f=cmd_resume)

    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
