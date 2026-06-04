def cmd_test_tool_calling(repo: str, model: str = None):
    """
    Test whether the configured local model correctly follows the manual JSON tool protocol.
    """
    from core.llm.ollama_client import OllamaClient, OllamaError, DEFAULT_MODEL
    from core.llm.prompts import SYSTEM_PROMPT
    from core.navigator.answer_contract import parse_response, ToolCall

    model = model or DEFAULT_MODEL
    client = OllamaClient(model=model)

    print(f"Testing tool protocol with model: {model}")

    if not client.is_available():
        print("ERROR: Ollama not running. Start with: ollama serve")
        raise SystemExit(1)

    test_prompt = "Find the symbol AssignVoucher. Use a tool first."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": test_prompt},
    ]

    print(f"Prompt: {test_prompt}")
    print("Calling model...")

    try:
        response = client.chat(messages)
    except OllamaError as e:
        print(f"ERROR calling model: {e}")
        raise SystemExit(1)

    print(f"\nModel response:\n{response}\n")

    parsed = parse_response(response)
    if isinstance(parsed, ToolCall):
        print("SUCCESS: Model followed tool protocol.")
        print(f"  tool: {parsed.tool}")
        print(f"  args: {parsed.args}")
    else:
        print("WARNING: Model does not reliably follow tool protocol. Use stricter prompt or switch model.")
        print(f"  Parsed: {type(parsed).__name__} — {parsed}")
        print("\nSuggestions:")
        print("  - Try: REPO_COACH_MODEL=qwen2.5-coder:7b repo-coach test-tool-calling")
        print("  - Ensure model is instruction-tuned (e.g. qwen2.5-coder:1.5b, not base)")
