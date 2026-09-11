"""评测门配置(E0):读环境变量 + 极简 .env(纯标准库,不引 python-dotenv)。

judge 配置键:EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY / EVAL_JUDGE_MODEL /
EVAL_JUDGE_MAX_TOKENS / EVAL_JUDGE_CONCURRENCY。不设任一 = judge 不可用(离线)。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path | None = None) -> None:
    """把仓库根 .env 里 KEY=value 行读进 os.environ(不覆盖已存在的变量)。

    `EVAL_DOTENV=0` 时**整段跳过** —— 测试需要真正「未配置 judge」的环境,而本函数用
    `setdefault` 会把 .env 里的真 key **重新灌回**,只删环境变量是删不干净的:
    本机 .env 有真 key,「未配置」用例会真的发起 HTTP 调用(既慢又花钱)。
    """
    if os.getenv("EVAL_DOTENV") == "0":
        return
    env_file = path or Path(ROOT / ".env")
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class JudgeConfig:
    """judge 端连接与成本上限(读 EVAL_JUDGE_*)。"""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    max_tokens: int = 512
    concurrency: int = 4
    timeout_s: float = 60.0
    retries: int = 1

    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def label(self) -> str:
        return f"{self.model}@{self.base_url}" if self.base_url else "offline"


def judge_config() -> JudgeConfig:
    _load_dotenv()
    return JudgeConfig(
        base_url=os.getenv("EVAL_JUDGE_BASE_URL") or None,
        api_key=os.getenv("EVAL_JUDGE_API_KEY") or None,
        model=os.getenv("EVAL_JUDGE_MODEL") or None,
        max_tokens=_int_env("EVAL_JUDGE_MAX_TOKENS", 512),
        concurrency=_int_env("EVAL_JUDGE_CONCURRENCY", 4),
    )
