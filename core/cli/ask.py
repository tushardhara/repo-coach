def cmd_ask(question: str, repo: str, verbose: bool = False, model: str = None):
    from core.navigator.graph_tools import GraphStore
    from core.llm.ollama_client import OllamaClient, OllamaError, DEFAULT_MODEL
    from core.navigator.tool_loop import AgentLoop
    import os

    repo = os.path.abspath(repo)
    graph = GraphStore(repo)
    if not graph.is_ready():
        print(f"Error: no index found at {repo}/.repo-coach/. Run: repo-coach build {repo}")
        raise SystemExit(1)

    client = OllamaClient(model=model or DEFAULT_MODEL)
    if not client.is_available():
        print("Error: Ollama not running. Start it with: ollama serve")
        raise SystemExit(1)

    loop = AgentLoop(graph, client, verbose=verbose)
    print(f"Question: {question}\n")
    answer, tool_log = loop.run(question)
    print(f"Tools used: {len(tool_log)}")
    for entry in tool_log:
        print(f"  {entry['tool']}({entry['args']}) -> {entry['result_summary'][:60]}...")
    print(f"\nAnswer:\n{answer}")
