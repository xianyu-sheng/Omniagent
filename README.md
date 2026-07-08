# OmniAgent

**MCP + 多模型 + 多范式，三合一的开源 terminal coding agent。**

[![CI](https://github.com/xianyu-sheng/omniagent/actions/workflows/ci.yml/badge.svg)](https://github.com/xianyu-sheng/omniagent/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)]()
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)]()

![OmniAgent terminal demo](docs/assets/terminal-demo.svg)

> 把 [Aider](https://aider.chat) 的多模型、[Claude Code](https://claude.com/claude-code) 的 MCP、还有学术圈热门的
> ReAct / Plan-Execute / Reflection 范式**做齐到一个** terminal agent 里。
> 18.9K 行 Python、8 种推理引擎、6 家模型 provider、20 项内置工具、930 项测试、MIT 开源。

---

## 三件合一

| 能力 | OmniAgent | 说明 |
| --- | --- | --- |
| **MCP 协议** | ✅ stdio + SSE 双传输 | 子进程用 `select` + 墙钟超时（B11 修复），不会被 `readline` 无限阻塞；进程退出用 `terminate()` + 兜底 `kill()`，无僵尸进程。 |
| **多模型路由** | ✅ 6 provider 一处配置 | DeepSeek / OpenAI / Claude / Gemini / Qwen / Ollama（含本地模型）；`provider_priority` + 断路器自动降级；per-provider `httpx.Client` 长连接池复用。 |
| **多范式引擎** | ✅ 8 种推理范式 | Direct / ReAct / Plan-Execute / Reflection / Novel（创意写作）+ 3 个组合引擎（Plan+React、Plan+Reflection、React+Reflection），同一套 REPL 内 `/mode` 切换。 |

> **对比一览**：[`docs/COMPARISON.md`](docs/COMPARISON.md) — 跟 Aider / Claude Code / OpenCode / Crush 在 8 个维度上对位。
>
> **架构详解**：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 8 种引擎切换图 + 路由层 + 三件套（Compactor / BudgetManager / CircuitBreaker）。

---

## Quick Start

```bash
git clone https://github.com/xianyu-sheng/omniagent.git
cd omniagent
pip install -e ".[dev]"
omniagent
```

进入 REPL 后：

```text
You: /setup                              # 配置 provider API key（存 ~/.omniagent/credentials.yaml）
You: /set_model deepseek/deepseek-v4-pro # 选默认模型
You: /mode plan-execute                  # 切到 Plan-Execute 范式
You: 帮我检查 tests 失败原因并给出修复方案
```

或直接用 `chat` 子命令一次跑：

```bash
omniagent chat -m deepseek/deepseek-v4-pro -m openai/gpt-4o "review this diff"
```

---

## 8 种推理范式，按任务难度切换

| 范式 | 适用场景 | 入口命令 |
| --- | --- | --- |
| `direct` | 简单问答、无需工具 | `/mode direct` |
| `react` | 工具调用循环（读文件 / 跑命令 / 调 MCP） | `/mode react` |
| `plan-execute` | 多步任务自动分解 + 拓扑并行执行（PlanDAG） | `/mode plan-execute` |
| `reflection` | 任务执行 + 独立审查者模型多轮评审 | `/mode reflection` |
| `novel` | 创意写作 / 长文续写 | `/mode novel` |
| `plan-react` | 先做计划，再 ReAct 工具循环 | `/mode plan-react` |
| `plan-reflection` | 计划 → 执行 → 独立模型审查 | `/mode plan-reflection` |
| `react-reflection` | 工具循环 → 独立模型审查 | `/mode react-reflection` |

---

## 20 项内置工具

| 类别 | 工具 |
| --- | --- |
| 文件 | `read_file` / `write_file` / `edit_file` / `edit_with_llm` / `batch_write` / `batch_edit` / `diff_preview` |
| 检索 | `search_files` / `code_index` / `ast_analyze` / `list_files` |
| 命令 | `command`（带 SSRF 拦截、命令注入收口、敏感路径黑名单） |
| Git | `git`（带危险命令拦截） |
| 网络 | `web_fetch`（带 SSRF 黑名单 + 已知安全域名白名单）/ `github_fetch` |
| 时间 | `datetime` |
| 动态 | `register_tool`（模式 2 only，RCE 收敛；`react_engine` 默认不暴露给 LLM） |
| MCP | `mcp_call` — 调用通过 `/mcp add` 注册的外部 MCP 服务器 |

v0.2.2 全量审查 20 个工具，修复 4 个真实 bug（天气 `city` 参数丢失、SSRF 误拦 `198.18.0.0/15`、`github_fetch` 格式校验崩溃等），新增 48 项工具冒烟测试。

---

## 工程化三件套

不是"能跑就行"，生产级 agent 该有的都有：

- **Compactor** — 6 步结构化压缩器，在 Token 窗口达 80% 时触发；引擎内每 5 轮自动压缩抑制 O(n²) 增长；支持持久化到 `~/.omniagent/compact/`。
- **BudgetManager** — 三阶段软预算（EXPLORE 25% / EXECUTE 50% / CONVERGE 25%），收束阶段禁用 7 个纯探索型工具，奖励机制（压缩 +N / 空洞补救 +N，`max_total_multiplier=2×` 封顶）。
- **CircuitBreaker** — 每工具独立断路器，**3 连续失败**触发熔断，**30s 冷却**（half_open 失败翻倍，上限 600s）；进程级 `GLOBAL_BREAKERS` 跨 run 累积。

配套：HollowDetector（15 正则 + 组合判定识别空洞回答）、ToolExecutor（7 阶段门面 + 参数幻觉校验）、EventBus（多订阅者 pub/sub）、DirectoryScout（项目目录扫描防路径幻觉）。

---

## 评测

```bash
# Mock eval（CI 跑通，20 任务）
python evals/runner.py --mode mock --output evals/reports/mock_report.md

# Real eval（需自配 API key，不进 CI）
python evals/runner.py --mode real --model deepseek/deepseek-v4-pro --output evals/reports/real_report.md
```

测试结果：[`docs/reports/v0.2.2/`](docs/reports/v0.2.2/) — REAL_TASK_TEST_REPORT（端到端 84 用例）+ VERIFICATION_REPORT（独立验证）。

---

## 安全

- API key 存 `~/.omniagent/credentials.yaml`，不入仓库
- 文件编辑前 `Confirm.ask` 显示 diff
- `command` / `git` 危险操作拦截或显式确认
- 敏感路径 / 凭证文件名黑名单
- `web_fetch` SSRF 黑名单（IPv4 私有网 / IPv6 ULA / 数字编码 IP / 重定向）+ 已知公共 API 白名单（`wttr.in` / `api.github.com` / `raw.githubusercontent.com` 等）
- `register_tool` 模式 1（任意 Python 导入）= RCE 收敛；模式 2（结构化参数）保留

---

## Project Rules

在项目根建 `.omniagent/rules.md` 即可引导 agent：

```markdown
# Project Rules
- Use Python 3.12.
- Prefer pytest for tests.
- Show diffs before editing tracked source files.
- Keep API keys and credentials out of the repository.
```

---

## 文档

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 8 种引擎切换图 + 路由层 + 三件套
- [`docs/COMPARISON.md`](docs/COMPARISON.md) — vs Aider / Claude Code / OpenCode / Crush
- [`docs/OPERATION_GUIDE.md`](docs/OPERATION_GUIDE.md) — REPL 命令手册
- [`docs/omniagent-design-spec-v1.1.html`](docs/omniagent-design-spec-v1.1.html) — 设计文档 v1.1
- [`docs/reports/v0.2.2/`](docs/reports/v0.2.2/) — 端到端测试报告 + 独立验证报告

---

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [Rich](https://github.com/Textualize/rich) — terminal UI
- [httpx](https://github.com/encode/httpx) — async HTTP client
- [PyYAML](https://github.com/yaml/pyyaml) — YAML parsing
