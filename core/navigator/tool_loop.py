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
from core.navigator.planner import classify_question, suggest_first_tool


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

        # Seed the first tool call from the planner so Qwen uses correct arg names
        strategy = classify_question(question)
        first_tool, first_args = suggest_first_tool(question, strategy)
        first_call_json = json.dumps({"action": "tool", "tool": first_tool, "args": first_args})
        try:
            first_result = self.graph.dispatch_tool(first_tool, first_args)
        except Exception as e:
            first_result = json.dumps({"error": str(e)})
        tool_call_count += 1
        tool_log.append({"tool": first_tool, "args": first_args, "result_summary": first_result[:200]})
        if self.verbose:
            print(f"[loop] seeded tool={first_tool} args={first_args}")
        messages.append({"role": "assistant", "content": first_call_json})
        messages.append({
            "role": "user",
            "content": format_tool_result(first_tool, first_args, first_result),
        })

        # For impact/flow strategies, seed a second tool call automatically
        # so Qwen doesn't short-circuit after the symbol lookup
        if strategy == "impact" and tool_call_count < MAX_TOOL_CALLS:
            try:
                syms = json.loads(first_result)
                sym_id = syms[0].get("id", "") if isinstance(syms, list) and syms else ""
            except Exception:
                sym_id = ""
            if sym_id:
                second_tool, second_args = "build_impact", {"symbol_id": sym_id}
                second_call_json = json.dumps({"action": "tool", "tool": second_tool, "args": second_args})
                try:
                    second_result = self.graph.dispatch_tool(second_tool, second_args)
                except Exception as e:
                    second_result = json.dumps({"error": str(e)})
                tool_call_count += 1
                tool_log.append({"tool": second_tool, "args": second_args, "result_summary": second_result[:200]})
                if self.verbose:
                    print(f"[loop] seeded tool={second_tool} args={second_args}")
                messages.append({"role": "assistant", "content": second_call_json})
                messages.append({
                    "role": "user",
                    "content": format_tool_result(second_tool, second_args, second_result),
                })

        elif strategy == "flow" and tool_call_count < MAX_TOOL_CALLS:
            try:
                routes = json.loads(first_result)
                handler_id = ""
                if isinstance(routes, list):
                    for r in routes:
                        hid = r.get("handler_id", "")
                        if hid and not any(w in hid.split(":")[-1].lower()
                                           for w in ("setup", "init", "main", "register", "routes")):
                            handler_id = hid
                            break
            except Exception:
                handler_id = ""
            if handler_id:
                second_tool, second_args = "build_flow", {"entrypoint_id": handler_id}
                second_call_json = json.dumps({"action": "tool", "tool": second_tool, "args": second_args})
                try:
                    second_result = self.graph.dispatch_tool(second_tool, second_args)
                except Exception as e:
                    second_result = json.dumps({"error": str(e)})
                tool_call_count += 1
                tool_log.append({"tool": second_tool, "args": second_args, "result_summary": second_result[:200]})
                if self.verbose:
                    print(f"[loop] seeded tool={second_tool} args={second_args}")
                messages.append({"role": "assistant", "content": second_call_json})
                messages.append({
                    "role": "user",
                    "content": format_tool_result(second_tool, second_args, second_result),
                })

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
