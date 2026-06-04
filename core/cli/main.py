#!/usr/bin/env python3
"""
repo-coach — Code Knowledge Agent CLI

Commands:
  build <repo_path>                         Index a repository
  ask <question>                            Ask a question (Qwen agent)
  explain --route <route> [repo]            Explain a route's flow
  impact --symbol <name> [repo]             Show impact of changing a symbol
  table <table_name> [repo]                 Show readers/writers of a DB table
  debug-context <question> [repo]           Show what evidence would be sent to Qwen
  test-tool-calling [repo]                  Test whether Qwen follows tool protocol

Environment:
  REPO_COACH_MODEL    Ollama model (default: qwen2.5-coder:1.5b)
  REPO_COACH_REPO     Default repo path (default: ~/Promotions)
"""
import sys
import os
import argparse

DEFAULT_REPO = os.environ.get("REPO_COACH_REPO", os.path.expanduser("~/Promotions"))


def main():
    parser = argparse.ArgumentParser(
        prog="repo-coach",
        description="RepoCoach v2 — Code Knowledge Agent",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # build
    p_build = sub.add_parser("build", help="Index a repository")
    p_build.add_argument("repo", nargs="?", default=DEFAULT_REPO)
    p_build.add_argument("--verbose", "-v", action="store_true", default=True)

    # ask
    p_ask = sub.add_parser("ask", help="Ask a question using Qwen agent")
    p_ask.add_argument("question")
    p_ask.add_argument("--repo", default=DEFAULT_REPO)
    p_ask.add_argument("--verbose", "-v", action="store_true")
    p_ask.add_argument("--model", default=None)

    # explain
    p_explain = sub.add_parser("explain", help="Explain a route's full flow")
    p_explain.add_argument("--route", required=True)
    p_explain.add_argument("repo", nargs="?", default=DEFAULT_REPO)

    # impact
    p_impact = sub.add_parser("impact", help="Show impact of changing a symbol")
    p_impact.add_argument("--symbol", required=True)
    p_impact.add_argument("repo", nargs="?", default=DEFAULT_REPO)

    # table
    p_table = sub.add_parser("table", help="Show DB table readers/writers")
    p_table.add_argument("table_name")
    p_table.add_argument("repo", nargs="?", default=DEFAULT_REPO)

    # debug-context
    p_debug = sub.add_parser("debug-context", help="Print evidence that would be sent to Qwen")
    p_debug.add_argument("question")
    p_debug.add_argument("repo", nargs="?", default=DEFAULT_REPO)

    # test-tool-calling
    p_test = sub.add_parser("test-tool-calling", help="Test Qwen tool protocol compliance")
    p_test.add_argument("repo", nargs="?", default=DEFAULT_REPO)
    p_test.add_argument("--model", default=None)

    args = parser.parse_args()

    if args.command == "build":
        from core.cli.build import cmd_build
        cmd_build(args.repo, verbose=args.verbose)
    elif args.command == "ask":
        from core.cli.ask import cmd_ask
        cmd_ask(args.question, repo=args.repo, verbose=args.verbose, model=args.model)
    elif args.command == "explain":
        from core.cli.explain import cmd_explain
        cmd_explain(args.route, repo=args.repo)
    elif args.command == "impact":
        from core.cli.impact import cmd_impact
        cmd_impact(args.symbol, repo=args.repo)
    elif args.command == "table":
        from core.cli.table import cmd_table
        cmd_table(args.table_name, repo=args.repo)
    elif args.command == "debug-context":
        from core.cli.debug_context import cmd_debug_context
        cmd_debug_context(args.question, repo=args.repo)
    elif args.command == "test-tool-calling":
        from core.cli.test_tool_calling import cmd_test_tool_calling
        cmd_test_tool_calling(repo=args.repo, model=args.model)


if __name__ == "__main__":
    main()
