# Xenon Agent Skills

Xenon 同时支持标准目录式 Agent Skill 和早期的 YAML 配方。标准技能可直接复用
Claude Code、Codex、Ark CLI 等生态常见的 `SKILL.md` 结构；旧技能无需迁移。

## 目录与覆盖顺序

Xenon 从宽到窄扫描四层目录，同名技能由后面的层级覆盖：

1. `~/.agents/skills/<name>/SKILL.md` — 多 Agent 共享的用户技能
2. `~/.xenon/skills/<name>/SKILL.md` — Xenon 用户技能
3. `<project>/.agents/skills/<name>/SKILL.md` — 多 Agent 共享的项目技能
4. `<project>/.xenon/skills/<name>/SKILL.md` — Xenon 项目技能

`~/.xenon/skills/*.yaml` 继续作为旧版 Xenon 配方加载。项目根通过 Git 或常见
语言项目标记确定；在家目录启动时不会把整个家目录当作项目。

## 最小格式

```markdown
---
name: code-review
description: Review a change against this project's engineering rules.
version: 1.0.0
metadata:
  requires:
    bins: [git]
---

# Code review

Read `references/checklist.md` only when a detailed review is requested.
```

技能名须为 1–64 位小写字母、数字、连字符或下划线；`description` 必填。
frontmatter 中未知的扩展字段不会影响加载，`metadata` 会保留供后续集成检查使用。

## 渐进式加载

- 启动、列举和路由阶段只保存 `name`、`description`、`version` 与 `metadata`。
- 用户通过 `/<name>` 或 `/skill run <name> [参数]` 命中后才读取正文。
- `references/`、`scripts/` 和 `assets/` 仅在技能工作流确实需要时通过工具读取；
  Xenon 不会因安装了大量技能而把全部资料注入每一轮上下文。
- 标准技能经 ReAct 工具链执行，因此文件、命令和 MCP 操作仍受原有权限面板与
  本轮执行边界保护。

## 安全与诊断

`SKILL.md` 最大 256 KiB。文本资源默认单文件最大 128 KiB，最多索引 500 个；
绝对路径、`..` 穿越、越界符号链接和二进制 Prompt 注入会被拒绝。一个技能损坏
只会隔离该技能，其他技能继续可用。

```text
/skill list
/skill run code-review 检查当前改动
/skill doctor
/skill delete code-review
```

`/skill doctor` 会列出实际扫描目录、标准/旧版技能数量和加载错误。删除上层同名
技能后，Xenon 会重新扫描，并自动恢复下层版本。
