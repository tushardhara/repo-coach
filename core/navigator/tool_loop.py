"""
Tool loop for RepoCoach Agent.
Orchestrates: user question → Qwen tool calls → tool execution → final answer.

Protocol:
  Model outputs: {"action":"tool","tool":"...","args":{...}}
  Tool executes, result appended to conversation.
  Model may call up to MAX_TOOL_CALLS tools.
  Then model outputs: {"action":"final","answer":"..."}
"""
import json
from typing import List, Tuple

from core.llm.ollama_client import OllamaClient, OllamaError
from core.llm.prompts import SYSTEM_PROMPT, MAX_TOOL_CALLS, format_tool_result, TOOL_CORRECTION_PROMPT
from core.navigator.answer_contract import parse_response, ToolCall, FinalAnswer, is_valid_tool_call
from core.navigator.graph_tools import GraphStore, VALID_TOOLS


class AgentLoop:
    def __init__(self, graph: GraphStore, client: OllamaClient, verbose: bool = False):
        self.graph = graph
        self.client = client
        self.verbose = verbose

    def run(self, question: str) -> Tuple[str, List[dict]]:
        """
        Run the agent loop for a question.
        Returns (final_answer_text, tool_call_log).
        tool_call_log: [{tool, args, result_summary}]
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        tool_log = []
        tool_call_count = 0
        retry_count = 0
        MAX_RETRIES = 2

        while tool_call_count < MAX_TOOL_CALLS:
            # Call model
            try:
                response_text = self.client.chat(messages)
            except OllamaError as e:
                return f"Error: Ollama not available — {e}", tool_log

            if self.verbose:
                print(f"[loop] model response: {response_text[:120]}")

            parsed = parse_response(response_text)

            if parsed is None:
                # Invalid JSON — retry once with correction prompt
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({"role": "user", "content": TOOL_CORRECTION_PROMPT})
                    continue
                else:
                    return (
                        f"Model did not follow tool protocol after {MAX_RETRIES} retries. "
                        f"Last response: {response_text[:200]}",
                        tool_log,
                    )

            retry_count = 0  # reset retry on valid parse

            if isinstance(parsed, FinalAnswer):
                return parsed.answer, tool_log

            # It's a ToolCall
            tc = parsed
            valid, err = is_valid_tool_call(tc, VALID_TOOLS)
            if not valid:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"Tool error: {err}. Try again."})
                continue

            # Execute tool
            try:
                result_json = self.graph.dispatch_tool(tc.tool, tc.args)
            except Exception as e:
                result_json = json.dumps({"error": str(e)})

            tool_call_count += 1
            result_summary = result_json[:200]
            tool_log.append({"tool": tc.tool, "args": tc.args, "result_summary": result_summary})

            if self.verbose:
                print(f"[loop] tool={tc.tool} args={tc.args} result={result_summary}")

            # Append to conversation
            messages.append({"role": "assistant", "content": response_text})
            messages.append({
                "role": "user",
                "content": format_tool_result(tc.tool, tc.args, result_json),
            })

        # Hit max tool calls — ask for best answer with what we have
        messages.append({
            "role": "user",
            "content": (
                f"You have used {MAX_TOOL_CALLS} tools. "
                "Now give your final answer based on what you found. "
                'Output: {"action":"final","answer":"..."}'
            ),
        })
        try:
            final_text = self.client.chat(messages)
        except OllamaError as e:
            return f"Max tools reached. Error getting final answer: {e}", tool_log

        final = parse_response(final_text)
        if isinstance(final, FinalAnswer):
            return final.answer, tool_log
        return final_text, tool_log  # fallback: return raw text
