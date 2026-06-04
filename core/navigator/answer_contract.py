"""
Parses the manual JSON tool protocol used by RepoCoach Agent.

Expected outputs from model:
  {"action":"tool","tool":"find_symbols","args":{"query":"AssignVoucher"}}
  {"action":"final","answer":"The function does X..."}
"""
import json
import re
from typing import Optional, Tuple


class ToolCall:
    def __init__(self, tool: str, args: dict):
        self.tool = tool
        self.args = args

    def __repr__(self) -> str:
        return f"ToolCall(tool={self.tool!r}, args={self.args!r})"


class FinalAnswer:
    def __init__(self, answer: str):
        self.answer = answer

    def __repr__(self) -> str:
        return f"FinalAnswer(answer={self.answer[:60]!r})"


# Python 3.10+ union syntax
ParsedResponse = ToolCall | FinalAnswer


def extract_json_block(text: str) -> Optional[str]:
    """Find first {...} block that spans to its matching closing brace."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse(raw: str) -> Optional[ParsedResponse]:
    """Attempt JSON parse and convert to ToolCall or FinalAnswer."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(obj, dict):
        return None

    action = obj.get("action")
    if action == "tool":
        tool = obj.get("tool", "")
        args = obj.get("args", {})
        if not isinstance(args, dict):
            args = {}
        return ToolCall(tool=tool, args=args)
    elif action == "final":
        answer = obj.get("answer", "")
        return FinalAnswer(answer=str(answer))

    return None


def parse_response(text: str) -> Optional[ParsedResponse]:
    """
    Try to parse a model response as a tool call or final answer.
    Returns ToolCall, FinalAnswer, or None (unparseable).

    Strategies:
    1. Direct JSON parse
    2. Strip markdown code block (```json ... ```) and parse
    3. Extract first {...} block via regex and parse
    4. Return None if nothing works
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()

    # Strategy 1: direct parse
    result = _try_parse(stripped)
    if result is not None:
        return result

    # Strategy 2: strip markdown code fences
    md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if md_match:
        result = _try_parse(md_match.group(1).strip())
        if result is not None:
            return result

    # Strategy 3: extract first {...} block
    block = extract_json_block(stripped)
    if block:
        result = _try_parse(block)
        if result is not None:
            return result

    # Strategy 4: truncated JSON fallback — extract partial answer from incomplete JSON
    # e.g. {"action":"final","answer":"some text... (cut off before closing "})
    trunc_match = re.search(r'"action"\s*:\s*"final".*?"answer"\s*:\s*"(.*)', stripped, re.DOTALL)
    if trunc_match:
        partial = trunc_match.group(1)
        # Strip trailing incomplete escape or quote
        partial = partial.rstrip('\\"').rstrip()
        if partial:
            return FinalAnswer(answer=partial + " [answer truncated]")

    return None


def is_valid_tool_call(tc: ToolCall, valid_tools: set) -> Tuple[bool, str]:
    """Returns (valid, error_message)."""
    if tc.tool not in valid_tools:
        return False, f"Unknown tool: {tc.tool}. Valid: {sorted(valid_tools)}"
    if not isinstance(tc.args, dict):
        return False, "args must be a dict"
    return True, ""
