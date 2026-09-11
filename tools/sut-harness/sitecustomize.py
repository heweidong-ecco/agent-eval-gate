"""在 langchain 1.x 环境里补回被移到 langchain_classic 的 legacy agent API。

被测仓库 api/requirements.txt 写 `langchain>=0.3.13`(无上界),镜像装到 1.x ——
而仓库代码用的是 0.3 时代的 API。这是**环境与依赖声明不匹配**,不是被测代码缺陷;
评测门不改被测一行,只在运行环境里补一层兼容别名(阶段3 R1b 同法,当时补在本地 venv)。
"""
try:
    import langchain.agents as _la
    from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
    _la.AgentExecutor = AgentExecutor
    _la.create_tool_calling_agent = create_tool_calling_agent
except Exception:  # 缺包时不阻断:让原始 ImportError 自己冒出来,便于定位
    pass
