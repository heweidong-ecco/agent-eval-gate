"""pytest 环境:让 `import eval_gate` 可用(包在 app/ 下)。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
