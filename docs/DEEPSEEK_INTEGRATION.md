# DeepSeek 收录准备与兼容性证据

> 状态：**收录候选，尚未获得 DeepSeek 官方认证或背书。**

本文用于准备向 DeepSeek 官方 GitHub 组织维护的
[`awesome-deepseek-integration`](https://github.com/deepseek-ai/awesome-deepseek-integration)
提交 Xenon 条目。进入该清单表示“被官方仓库收录为社区集成”，不等同于
“DeepSeek 官方指定工具”。

## 当前 API 兼容基线

核对日期：2026-07-21。

| 官方要求 | Xenon 实现 | 验证位置 |
|----------|------------|----------|
| 正式模型为 `deepseek-v4-pro` / `deepseek-v4-flash` | 在线读取 `/models`；离线只回退到两个正式模型 | `xenon/repl/provider_registry.py` |
| 1M 上下文 | 注册 V4 模型时默认设置 1,000,000 | `xenon/repl/model_registry.py` |
| 思考模式工具续轮 | 保留 `reasoning_content`、assistant `tool_calls` 和匹配 `tool_call_id` 的结果 | `xenon/utils/llm_client.py`、`xenon/engine/base.py` |
| 强制工具选择 | DeepSeek V4 使用 `required` / `none` / 指定函数时，仅对该请求关闭思考模式 | `xenon/utils/llm_client.py` |
| 上下文缓存 usage | 读取命中/未命中 token，按模型显示命中率和费用 | `xenon/utils/deepseek_cache.py` |
| 当前人民币价格 | Flash: 0.02 / 1 / 2；Pro: 0.025 / 3 / 6（hit / miss / output，元/百万 token） | `xenon/utils/deepseek_cache.py` |
| 工具调用 | DeepSeek V4 为 ReAct 主模型时自动启用原生 function calling，失败时分层降级到 JSON schema / 文本协议 | `xenon/engine/react_engine.py`、`xenon/engine/base.py` |

官方依据：

- [DeepSeek 模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [DeepSeek 思考模式与工具续轮](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode)
- [Awesome DeepSeek Integrations](https://github.com/deepseek-ai/awesome-deepseek-integration)

## 本地证据命令

```bash
python -m pip install -e ".[dev]"
ruff check xenon
pytest tests xenon/tests -m "not live and not e2e" -q
pytest tests/e2e -m e2e -q
xenon --version
```

CI 还会在 Python 3.10、3.11、3.12 上重复离线测试，执行覆盖率门槛和发行包校验。
需要真实 DeepSeek Key 或公网的测试均标记为 `live`，不会让外部网络波动污染离线 CI。

## 建议提交条目

该官方仓库在核对日期没有单独的 `CONTRIBUTING.md`；现有项目直接以三列表格维护。
Xenon 作为终端工具，建议放在 `Others` 分类：

```html
<tr>
    <td style="font-size: 48px">✦</td>
    <td><a href="https://github.com/xianyu-sheng/Xenon">Xenon</a></td>
    <td>An open-source terminal AI coding workspace with first-class DeepSeek V4 support, native tool calling, permission-gated file and shell tools, context-cache cost tracking, resumable sessions, and MCP integration.</td>
</tr>
```

建议 PR 标题：

```text
Add Xenon terminal coding workspace
```

建议 PR 正文：

```text
Xenon is an open-source terminal AI coding workspace with direct DeepSeek API
support. It discovers available models from /models, supports DeepSeek V4
thinking-mode tool calls, reports context-cache usage and estimated CNY cost,
and includes permission-gated coding tools, session recovery, and MCP support.

Repository: https://github.com/xianyu-sheng/Xenon
License: MIT
Platforms: Linux, macOS, Windows
Python: 3.10+
```

## 提交前检查清单

- [ ] `main` 分支 CI 全绿，并保留可点击的 CI / coverage badge
- [ ] 发布与源码一致的 `v0.6.3` tag 和 GitHub Release
- [ ] README 中不使用“官方”“指定”“认证”等未经授权的表述
- [ ] README 演示图与当前双线输入框、固定底栏、无边框回复一致
- [ ] 从全新虚拟环境按公开安装命令完成一次 DeepSeek 对话和一次工具调用
- [ ] 提交表格条目时保持英文描述简短、可验证，不使用竞品贬损性比较

## 距离“成熟终端编程工具”的剩余差距

本轮已经覆盖权限、原子写入、模型恢复、跨轮轨迹、GitHub URL、Plan 失败传播、
离线 CI 和 DeepSeek V4 工具协议。尚未阻塞官方清单收录，但以下能力仍决定长期成熟度：

1. **真实任务成功率**：仓库现有公开评测仍为 20 个任务、45% 成功率；应扩大固定任务集，并把失败分类和版本趋势放进 CI 或定期报告。
2. **系统级隔离**：当前以路径、参数和权限闸门为主，不等于容器/namespace 级 shell 沙箱；高风险无人值守场景仍需更强隔离。
3. **发行工程**：需要稳定的 PyPI 发布、校验和回滚流程；单文件静态二进制、签名和 SBOM 尚未提供。
4. **编辑器协议**：Reasonix 已公开 ACP 接口规范，Xenon 当前仍以 TUI 为主；若要进入 IDE/桌面宿主，需要 ACP 或等价协议层。
5. **跨平台真实回归**：CI 使用 Linux；Windows/macOS 的终端键位、剪贴板、PTY 和全局热键仍需要独立 runner 验证。

完成官方清单 PR 后，若目标进一步升级为合作或官方推荐，应通过 DeepSeek API 文档列出的
`api-service@deepseek.com` 联系官方，并提供版本化评测、活跃用户数据、安全模型和维护承诺。
