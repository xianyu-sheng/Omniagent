"""Textual TUI — 借鉴 KamaClaude 的终端 UI 设计。

基于 Textual 框架的现代化终端界面，替代原有 Rich-based console REPL。

特性:
- 分栏布局: 对话区 + 思考/状态面板
- 实时事件流: 通过 EventBus 订阅实时更新
- 权限审批弹窗: Modal 对话框交互式审批
- 子任务状态: 实时显示 BackgroundTaskRegistry 任务
- 快捷键: Ctrl+P 切换模式, Ctrl+M 切换模型, / 斜杠命令
- C/S 集成: 通过 SocketClient 连接到 omniagent-core daemon

启动:
    omniagent-tui           # 交互式 TUI
    omniagent-tui --connect # 连接到 daemon
"""

__version__ = "0.1.0"
