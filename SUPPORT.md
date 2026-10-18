# 获取帮助

## 先看这些

| 你遇到的问题 | 先看 |
|---|---|
| 这是什么、怎么装 | `README.md` |
| 常见问题(密钥 / 429 / exit code / 语料) | **`docs/FAQ.md`** |
| 全部文档导航 | **`docs/README.md`** |
| 接自己的被测 | `docs/接入新被测.md` |
| 本机环境坑(TLS / IPv6 / 模型名) | `docs/部署.md §6` |
| 故障场景与演练 | `docs/故障场景应对手册.md` |
| 完整 CLI 参数 | `docs/CLI.md` |

## 提问 / 报 bug

- **Bug / 功能请求**:开 GitHub issue(用 `.github/ISSUE_TEMPLATE/` 的模板);
- **安全问题**:⛔ 不要开公开 issue → 见 `SECURITY.md`;
- **使用问题**:也走 issue,请贴上:
  - 版本(`eval-gate --help` 或 `git rev-parse --short HEAD`);
  - 复现命令;
  - 报错全文 / `eval/runs/<run_id>.local.json` 的关键字段(**先脱敏**)。

## 支持边界

- 单人维护、**尽力而为,无 SLA**;
- 不提供商业支持 / 托管服务;
- 被测系统自身的故障请找被测方。
