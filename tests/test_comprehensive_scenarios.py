"""
OmniAgent 全场景真实测试
=======================
测试 OMniAgent 在多种真实场景下的表现：
- 日常对话（问候、闲聊）
- 通用知识查询
- 实时信息查询（天气、时间）
- 代码生成
- 项目分析
- 行业场景（DevOps、数据分析）
- 混合任务

每个测试都会真实调用 LLM，记录结果并检测问题。
"""

import sys
import io
import json
import time
import re
import traceback
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule

console = Console()

# ── 测试配置 ────────────────────────────────────────────
MODEL = ["deepseek/deepseek-v4-pro"]
TIMEOUT_PER_TEST = 180  # 3 分钟超时

@dataclass
class TestResult:
    name: str
    category: str
    input_text: str
    mode_used: str = ""
    output: str = ""
    tools_used: int = 0
    elapsed: float = 0.0
    error: str = ""
    checks: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.error and all(self.checks.values())

    @property
    def check_summary(self) -> str:
        return ", ".join(f"{k}:{'✓' if v else '✗'}" for k, v in self.checks.items())


def check_quality(result: TestResult, scenario_type: str) -> dict:
    """根据场景类型做质量检查"""
    checks = {}
    output = result.output
    output_len = len(output)

    # 基础检查：不能太短
    if "chat" in scenario_type or "knowledge" in scenario_type:
        checks["min_length_20"] = output_len >= 20
    elif "analysis" in scenario_type:
        checks["min_length_200"] = output_len >= 200
    else:
        checks["min_length_10"] = output_len >= 10

    # 不能是空洞回复
    hollow_patterns = [
        r"^(继续|我将|接下来|首先).{0,20}$",
        r"^(好的|收到|明白|了解).{0,10}$",
    ]
    is_hollow = any(re.match(p, output.strip()) for p in hollow_patterns)
    checks["not_hollow"] = not is_hollow

    # 不能有 JSON 裸输出
    checks["no_raw_json"] = not output.strip().startswith("{")

    # 不能有真实的错误消息（排除出现在代码块、技术分析报告中的）
    # 策略：先检查输出是否明显是成功的内容（长报告、有结构），如果是则跳过通用错误检测
    is_structured_report = (
        len(output) > 1000
        and len(re.findall(r"##|###|\*\*|```|技术栈|架构|分析|建议", output)) >= 4
    )
    if is_structured_report:
        # 对于结构化报告，只检测最严重的系统级错误
        critical_errors = [
            r"Traceback\s*\(most recent call last\)",  # Python Traceback
            r"(?:所有模型|全部模型|模型调用).{0,5}(?:失败|不可用|错误)",  # 所有模型调用失败
        ]
        has_real_error = any(re.search(p, output, re.I) for p in critical_errors)
    else:
        # 对于其他输出，用更严格的检测
        text_no_code = re.sub(r"```[\s\S]*?```", "", output)
        text_no_code = re.sub(r"`[^`]+`", "", text_no_code)
        real_error_patterns = [
            r"❌\s*(?:错误|失败|异常|Error|Exception|Failed)",
            r"Traceback\s*\(most recent call last\)",
            r"(?:所有模型|全部模型|模型调用).{0,5}(?:失败|不可用|错误)",
        ]
        has_real_error = any(re.search(p, text_no_code, re.I) for p in real_error_patterns)
    checks["no_error_markers"] = not has_real_error

    # 场景特定检查
    if "weather" in scenario_type:
        checks["has_weather_info"] = any(w in output for w in ["温度", "天气", "°C", "℃", "晴", "雨", "阴", "多云"])
    elif "time" in scenario_type:
        checks["has_time_info"] = any(t in output for t in ["时间", "点", "分", "秒", "202", "星期", "月", "日"])
    elif "code_gen" in scenario_type:
        checks["has_code"] = "```" in output or "def " in output or "class " in output
    elif "analysis" in scenario_type:
        checks["has_structure"] = any(s in output for s in ["##", "分析", "代码", "结构", "问题", "建议", "改进"])
    elif "knowledge" in scenario_type:
        checks["has_substance"] = output_len >= 50

    return checks


def run_engine_test(
    engine_type: str,
    user_input: str,
    model_ids: list[str],
    **engine_kwargs,
) -> tuple[str, float, int]:
    """运行指定引擎并返回 (结果, 耗时, 工具调用次数)"""
    from omniagent.engine.context import AgentContext
    from omniagent.engine.callbacks import EngineCallback

    class ToolCounter(EngineCallback):
        def __init__(self):
            self.tool_count = 0
            self.actions = []
        def on_act(self, action, params):
            self.tool_count += 1
            self.actions.append((action, params))
        def on_warning(self, msg): pass
        def on_step(self, *args): pass
        def on_step_done(self, *args): pass
        def on_error(self, msg): pass
        def on_finish(self, result): pass

    cb = ToolCounter()
    ctx = AgentContext()

    t0 = time.time()

    if engine_type == "react":
        from omniagent.engine.react_engine import ReActEngine
        engine = ReActEngine(model_priority=model_ids, max_iterations=10, callback=cb, **engine_kwargs)
        result = engine.run(user_input, context=ctx)
    elif engine_type == "plan_execute":
        from omniagent.engine.plan_execute_engine import PlanExecuteEngine
        engine = PlanExecuteEngine(model_priority=model_ids, max_steps=15, callback=cb, **engine_kwargs)
        result = engine.run(user_input, context=ctx)
    elif engine_type == "plan_react":
        from omniagent.engine.combined_engines import PlanReactEngine
        engine = PlanReactEngine(model_priority=model_ids, max_steps=10, react_iterations=6, callback=cb, **engine_kwargs)
        result = engine.run(user_input, context=ctx)
    elif engine_type == "plan_reflection":
        from omniagent.engine.combined_engines import PlanReflectionEngine
        engine = PlanReflectionEngine(model_priority=model_ids, max_steps=15, review_rounds=1, callback=cb, **engine_kwargs)
        result = engine.run(user_input, context=ctx)
    elif engine_type == "react_reflection":
        from omniagent.engine.combined_engines import ReactReflectionEngine
        engine = ReactReflectionEngine(model_priority=model_ids, react_iterations=8, review_rounds=1, callback=cb, **engine_kwargs)
        result = engine.run(user_input, context=ctx)
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")

    elapsed = time.time() - t0
    return result, elapsed, cb.tool_count


def test_direct_llm(user_input: str, model_ids: list[str]) -> tuple[str, float]:
    """纯 LLM 调用（direct 模式）"""
    from omniagent.utils.llm_client import chat_completion

    messages = [
        {"role": "system", "content": "你是 OmniAgent-CLI 的 AI 编程助手。请用中文回答。"},
        {"role": "user", "content": user_input},
    ]

    t0 = time.time()
    for model_id in model_ids:
        try:
            result = chat_completion(model_id, messages, max_tokens=2048, temperature=0.5)
            if result and result.strip():
                elapsed = time.time() - t0
                return result, elapsed
        except Exception:
            continue
    return "所有模型调用失败", time.time() - t0


# ── 测试场景定义 ──────────────────────────────────────────

SCENARIOS = [
    # ═══ 类别 1: 日常对话 ═══
    {
        "name": "1.1-问候自我介绍",
        "category": "chat",
        "input": "你好，请简单介绍一下你自己和你能做什么",
        "expect_mode": "direct",
        "use_engine": None,  # None = direct LLM
    },
    {
        "name": "1.2-日常闲聊",
        "category": "chat",
        "input": "周末在家无聊，有什么建议可以打发时间吗？",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "1.3-中文理解",
        "category": "chat",
        "input": "请解释一下'塞翁失马，焉知非福'这句成语的含义",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 2: 实时信息查询 ═══
    {
        "name": "2.1-天气查询",
        "category": "weather",
        "input": "今天重庆天气怎么样？",
        "expect_mode": "react",
        "use_engine": "react",
    },
    {
        "name": "2.2-时间查询",
        "category": "time",
        "input": "现在几点了？今天是星期几？",
        "expect_mode": "react",
        "use_engine": "react",
    },

    # ═══ 类别 3: 通用知识 ═══
    {
        "name": "3.1-编程概念",
        "category": "knowledge",
        "input": "什么是面向对象编程的SOLID原则？请简要说明每个原则。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "3.2-技术对比",
        "category": "knowledge",
        "input": "比较一下 React 和 Vue.js 的核心设计理念，各自适合什么场景？",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "3.3-算法解释",
        "category": "knowledge",
        "input": "什么是动态规划？请用一个简单的例子说明它的思想。",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 4: 代码生成 ═══
    {
        "name": "4.1-简单函数",
        "category": "code_gen",
        "input": "用Python写一个函数，判断一个字符串是否是回文（忽略大小写和空格）。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "4.2-脚本生成",
        "category": "code_gen",
        "input": "写一个Python脚本，读取一个JSON文件，统计里面出现了多少种不同的key，并按出现频率从高到低排序。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "4.3-正则表达式",
        "category": "code_gen",
        "input": "写一个正则表达式来验证一个字符串是否是有效的IPv4地址。并给出Python使用示例。",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 5: 项目分析（需要工具） ═══
    {
        "name": "5.1-项目代码分析",
        "category": "analysis",
        "input": (
            "分析 D:\\语音版的日历工具 这个项目的代码质量和架构。"
            "请用 list_files 先了解项目结构，然后读核心文件，给出具体分析。"
        ),
        "expect_mode": "react",
        "use_engine": "react",
    },

    # ═══ 类别 6: DevOps & 运维 ═══
    {
        "name": "6.1-Docker部署",
        "category": "knowledge",
        "input": "如何在Docker中部署一个Flask应用？请给出完整的Dockerfile和多阶段构建示例。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "6.2-CI/CD",
        "category": "knowledge",
        "input": "解释一下GitHub Actions的workflow文件结构，并给出一个Python项目的CI示例。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "6.3-监控日志",
        "category": "knowledge",
        "input": "在生产环境中，如何构建一个高效的日志系统？需要考虑哪些方面？",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 7: 数据分析 ═══
    {
        "name": "7.1-Pandas处理",
        "category": "knowledge",
        "input": "Pandas中如何处理缺失数据？请列出常用方法并比较它们的适用场景。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "7.2-数据可视化",
        "category": "knowledge",
        "input": "用Matplotlib创建一个展示不同类别销售数据的柱状图，请给出完整代码。",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 8: 安全 ═══
    {
        "name": "8.1-SQL注入",
        "category": "knowledge",
        "input": "什么是SQL注入攻击？如何在使用Python的web框架时防止它？请给出具体示例。",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "8.2-常见漏洞",
        "category": "knowledge",
        "input": "列出Web应用中OWASP Top 5安全风险，并给出每种风险的Python防护方案。",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 9: 架构与设计 ═══
    {
        "name": "9.1-微服务设计",
        "category": "knowledge",
        "input": "设计一个电商系统的微服务架构。需要哪些服务？服务间如何通信？",
        "expect_mode": "direct",
        "use_engine": None,
    },
    {
        "name": "9.2-数据库设计",
        "category": "knowledge",
        "input": "为一个博客系统设计数据库Schema。包括用户、文章、评论、标签等实体。请给出SQL DDL。",
        "expect_mode": "direct",
        "use_engine": None,
    },

    # ═══ 类别 10: Plan-Execute 模式专项 ═══
    {
        "name": "10.1-Plan模式分析",
        "category": "analysis",
        "input": (
            "请分析 D:\\语音版的日历工具 项目的以下方面：\n"
            "1. 项目用途和技术栈\n"
            "2. 代码架构和模块划分\n"
            "3. 代码质量评估\n"
            "4. 给出至少3条具体改进建议\n"
            "请务必实际读取项目文件进行分析。"
        ),
        "expect_mode": "plan_execute",
        "use_engine": "plan_execute",
    },
]


def run_all_tests():
    """运行所有测试场景"""
    results: list[TestResult] = []

    console.print(Rule("🚀 OmniAgent 全场景真实测试"))
    console.print(f"测试场景数: {len(SCENARIOS)}")
    console.print(f"模型: {MODEL[0]}")
    console.print(f"超时: {TIMEOUT_PER_TEST}s/测试")
    console.print()

    for i, scenario in enumerate(SCENARIOS):
        name = scenario["name"]
        category = scenario["category"]
        user_input = scenario["input"]
        use_engine = scenario.get("use_engine")

        console.print(Rule(f"[{i+1}/{len(SCENARIOS)}] {name}"))
        console.print(f"[dim]输入: {user_input[:120]}...[/dim]")

        result = TestResult(
            name=name,
            category=category,
            input_text=user_input,
            mode_used=use_engine or "direct",
        )

        try:
            t0 = time.time()

            if use_engine:
                # 使用指定引擎
                console.print(f"[cyan]引擎: {use_engine}[/cyan]")
                output, elapsed, tools = run_engine_test(
                    use_engine, user_input, MODEL
                )
                result.tools_used = tools
            else:
                # 纯 LLM 调用（direct 模式）
                console.print("[dim]模式: direct (纯 LLM)[/dim]")
                output, elapsed = test_direct_llm(user_input, MODEL)
                result.tools_used = 0

            result.output = output
            result.elapsed = elapsed
            result.checks = check_quality(result, category)

            # 显示结果摘要
            output_preview = output[:300].replace('\n', '\\n')
            console.print(f"[dim]输出预览: {output_preview}...[/dim]")
            console.print(f"[dim]耗时: {elapsed:.0f}s | 工具调用: {result.tools_used} | 输出长度: {len(output)}[/dim]")

        except Exception as e:
            result.error = str(e)
            result.elapsed = time.time() - t0
            result.checks = {}
            console.print(f"[red]错误: {e}[/red]")
            traceback.print_exc()

        results.append(result)

        # 显示该测试的检查结果
        status_str = "✓ PASS" if result.passed else "✗ FAIL"
        status_color = "green" if result.passed else "red"
        console.print(f"[{status_color}]{status_str}[/{status_color}] {result.check_summary}")

    return results


def print_summary(results: list[TestResult]):
    """打印汇总报告"""
    console.print(Rule("📊 测试汇总报告"))

    # 按类别汇总
    categories = {}
    for r in results:
        cat = r.category
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0, "total_time": 0}
        categories[cat]["total"] += 1
        if r.passed:
            categories[cat]["passed"] += 1
        categories[cat]["total_time"] += r.elapsed

    # 类别汇总表
    cat_table = Table(title="📂 按类别汇总")
    cat_table.add_column("类别", style="cyan")
    cat_table.add_column("通过/总计", style="bold")
    cat_table.add_column("通过率", style="green")
    cat_table.add_column("总耗时", style="dim")

    for cat, stats in sorted(categories.items()):
        rate = f"{stats['passed']/stats['total']*100:.0f}%"
        time_str = f"{stats['total_time']:.0f}s"
        cat_table.add_row(cat, f"{stats['passed']}/{stats['total']}", rate, time_str)

    console.print(cat_table)

    # 详细结果表
    detail_table = Table(title="📋 详细测试结果")
    detail_table.add_column("测试", style="cyan")
    detail_table.add_column("引擎", style="magenta")
    detail_table.add_column("耗时", style="dim")
    detail_table.add_column("工具", style="yellow")
    detail_table.add_column("输出长度", style="dim")
    detail_table.add_column("结果", style="bold")
    detail_table.add_column("检查详情", style="dim")

    pass_count = 0
    fail_count = 0

    for r in results:
        status = "✓ PASS" if r.passed else "✗ FAIL"
        status_style = "green" if r.passed else "red"
        detail_table.add_row(
            r.name,
            r.mode_used,
            f"{r.elapsed:.0f}s",
            str(r.tools_used),
            str(len(r.output)),
            f"[{status_style}]{status}[/{status_style}]",
            r.check_summary if not r.passed else "",
        )
        if r.passed:
            pass_count += 1
        else:
            fail_count += 1

    console.print(detail_table)

    # 总体统计
    total = len(results)
    total_time = sum(r.elapsed for r in results)
    console.print()
    console.print(Panel(
        f"总测试: {total} | 通过: [green]{pass_count}[/green] | 失败: [red]{fail_count}[/red] | "
        f"通过率: [bold]{pass_count/total*100:.1f}%[/bold] | 总耗时: {total_time:.0f}s",
        title="📈 总体统计",
    ))

    # 失败详情
    failures = [r for r in results if not r.passed]
    if failures:
        console.print(Rule("🔴 失败详情"))
        for r in failures:
            console.print(f"\n[bold red]✗ {r.name}[/bold red]")
            if r.error:
                console.print(f"  [red]异常: {r.error}[/red]")
            else:
                failed_checks = {k: v for k, v in r.checks.items() if not v}
                console.print(f"  [yellow]失败的检查: {failed_checks}[/yellow]")
                console.print(f"  [dim]输出前200字: {r.output[:200]}[/dim]")

    return pass_count, fail_count


if __name__ == "__main__":
    results = run_all_tests()
    passed, failed = print_summary(results)
    sys.exit(0 if failed == 0 else 1)
