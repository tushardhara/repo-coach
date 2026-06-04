#!/usr/bin/env python3
"""
graph_builder.py — RAG-ready codebase graph for RepoCoach

Two-phase pipeline (same approach as understand-anything):
  Phase 1 (fast, free): Deterministic structure extraction via AST/regex.
                        Produces nodes with lineRange but no summaries.
  Phase 2 (optional):   LLM enrichment — calls claude -p per file to generate
                        per-function summaries, tags, complexity.
                        Run with --enrich to activate.

Node schema (mirrors understand-anything):
  id, type, name, filePath, lineRange, signature, docstring,
  summary, tags, complexity

Usage:
  # Build (structure only, fast)
  python3 scripts/graph_builder.py --repo ~/Promotions --out ~/finetune-workspace/graph.json

  # Build + enrich with LLM summaries (slower, much better RAG quality)
  python3 scripts/graph_builder.py --repo ~/Promotions --out ~/finetune-workspace/graph.json --enrich

  # Query (uses summaries + real code snippets when repo-root provided)
  python3 scripts/graph_builder.py --query "wallet config" --repo-root ~/Promotions
"""
import ast, os, json, re, sys, subprocess, argparse
from pathlib import Path

SKIP_DIRS  = {'node_modules', '.git', '__pycache__', 'dist', 'build', '.venv', 'venv', 'vendor'}
DEFAULT_GRAPH = os.path.expanduser('~/finetune-workspace/graph.json')
EXT_LANG   = {'.go': 'go', '.py': 'python', '.js': 'javascript',
              '.ts': 'typescript', '.jsx': 'javascript', '.tsx': 'typescript'}
MAX_SNIPPET = 12   # max lines per code snippet in query output
ENRICH_MAX_FILE_LINES = 300  # skip LLM enrichment for files longer than this


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _line_of(src: str, offset: int) -> int:
    return src[:offset].count('\n') + 1


def _go_func_end(lines: list, start_idx: int) -> int:
    """Scan forward from start_idx counting braces; return 1-based closing line."""
    depth = 0
    for i in range(start_idx, min(start_idx + 100, len(lines))):
        depth += lines[i].count('{') - lines[i].count('}')
        if depth == 0 and i > start_idx:
            return i + 1
    return start_idx + 30  # fallback


def _go_doc(lines: list, func_idx: int) -> str:
    """Extract godoc comment block immediately above a Go function."""
    out = []
    i = func_idx - 1
    while i >= 0 and lines[i].strip().startswith('//'):
        out.insert(0, lines[i].strip().lstrip('/').strip())
        i -= 1
    return ' '.join(out)[:200]


def _brace_end(lines: list, start_idx: int) -> int:
    depth = 0
    for i in range(start_idx, min(start_idx + 120, len(lines))):
        depth += lines[i].count('{') - lines[i].count('}')
        if depth == 0 and i > start_idx:
            return i + 1
    return start_idx + 30


# ─── Phase 1: Structure extraction ───────────────────────────────────────────

def extract_python(path: str, rel: str) -> list[dict]:
    """Return list of GraphNode dicts for a Python file."""
    try:
        source = open(path, errors='ignore').read()
        tree   = ast.parse(source)
    except SyntaxError:
        return []

    nodes = []
    nodes.append({
        'id': f"file:{rel}", 'type': 'file', 'name': Path(rel).name,
        'filePath': rel, 'lineRange': None, 'signature': '',
        'docstring': '', 'summary': '', 'tags': [], 'complexity': 'simple',
    })

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            nodes.append({
                'id':        f"function:{rel}:{node.name}",
                'type':      'function',
                'name':      node.name,
                'filePath':  rel,
                'lineRange': [node.lineno, getattr(node, 'end_lineno', node.lineno)],
                'signature': f"def {node.name}({', '.join(args)})",
                'docstring': (ast.get_docstring(node) or '')[:200],
                'summary': '', 'tags': [], 'complexity': 'simple',
            })
        elif isinstance(node, ast.ClassDef):
            bases = []
            try:
                bases = [ast.unparse(b) for b in node.bases]
            except Exception:
                pass
            nodes.append({
                'id':        f"class:{rel}:{node.name}",
                'type':      'class',
                'name':      node.name,
                'filePath':  rel,
                'lineRange': [node.lineno, getattr(node, 'end_lineno', node.lineno)],
                'signature': f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                'docstring': (ast.get_docstring(node) or '')[:200],
                'summary': '', 'tags': [], 'complexity': 'simple',
            })
    return nodes


def extract_go(path: str, rel: str) -> list[dict]:
    try:
        src   = open(path, errors='ignore').read()
        lines = src.splitlines(keepends=True)
    except Exception:
        return []

    nodes = []
    nodes.append({
        'id': f"file:{rel}", 'type': 'file', 'name': Path(rel).name,
        'filePath': rel, 'lineRange': None, 'signature': '',
        'docstring': '', 'summary': '', 'tags': [], 'complexity': 'simple',
    })

    for m in re.finditer(r'^func\s+(?:\([^)]*\)\s+)?(\w+)\s*(\([^)]*\))', src, re.MULTILINE):
        ls  = _line_of(src, m.start())
        le  = _go_func_end(lines, ls - 1)
        doc = _go_doc(lines, ls - 1)
        nodes.append({
            'id':        f"function:{rel}:{m.group(1)}",
            'type':      'function',
            'name':      m.group(1),
            'filePath':  rel,
            'lineRange': [ls, le],
            'signature': m.group(0)[:120].replace('\n', ' '),
            'docstring': doc,
            'summary': '', 'tags': [], 'complexity': 'simple',
        })

    for m in re.finditer(r'^type\s+(\w+)\s+(struct|interface)\b', src, re.MULTILINE):
        ls = _line_of(src, m.start())
        nodes.append({
            'id':        f"class:{rel}:{m.group(1)}",
            'type':      'class',
            'name':      m.group(1),
            'filePath':  rel,
            'lineRange': [ls, ls],
            'signature': f"type {m.group(1)} {m.group(2)}",
            'docstring': '',
            'summary': '', 'tags': [], 'complexity': 'simple',
        })
    return nodes


def extract_js(path: str, rel: str) -> list[dict]:
    try:
        src   = open(path, errors='ignore').read()
        lines = src.splitlines(keepends=True)
    except Exception:
        return []

    nodes = []
    nodes.append({
        'id': f"file:{rel}", 'type': 'file', 'name': Path(rel).name,
        'filePath': rel, 'lineRange': None, 'signature': '',
        'docstring': '', 'summary': '', 'tags': [], 'complexity': 'simple',
    })

    for m in re.finditer(r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(\([^)]*\))', src, re.MULTILINE):
        ls = _line_of(src, m.start())
        nodes.append({
            'id': f"function:{rel}:{m.group(1)}", 'type': 'function',
            'name': m.group(1), 'filePath': rel,
            'lineRange': [ls, _brace_end(lines, ls - 1)],
            'signature': m.group(0)[:120], 'docstring': '',
            'summary': '', 'tags': [], 'complexity': 'simple',
        })
    for m in re.finditer(r'^(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(', src, re.MULTILINE):
        ls = _line_of(src, m.start())
        nodes.append({
            'id': f"function:{rel}:{m.group(1)}", 'type': 'function',
            'name': m.group(1), 'filePath': rel,
            'lineRange': [ls, _brace_end(lines, ls - 1)],
            'signature': m.group(0)[:80], 'docstring': '',
            'summary': '', 'tags': [], 'complexity': 'simple',
        })
    for m in re.finditer(r'^(?:export\s+)?class\s+(\w+)', src, re.MULTILINE):
        ls = _line_of(src, m.start())
        nodes.append({
            'id': f"class:{rel}:{m.group(1)}", 'type': 'class',
            'name': m.group(1), 'filePath': rel,
            'lineRange': [ls, ls], 'signature': m.group(0)[:80],
            'docstring': '', 'summary': '', 'tags': [], 'complexity': 'simple',
        })
    return nodes


# ─── Phase 2: LLM enrichment ─────────────────────────────────────────────────

_ENRICH_PROMPT = """\
Analyze this {lang} file and return ONLY valid JSON (no markdown, no explanation).

Schema:
{{
  "fileSummary": "1-2 sentence plain-English description of what this file does",
  "functionSummaries": {{"FuncName": "1 sentence description", ...}},
  "classSummaries": {{"ClassName": "1 sentence description", ...}},
  "tags": ["tag1", "tag2", ...],
  "complexity": "simple" | "moderate" | "complex"
}}

File: {path}
```
{code}
```"""


def _enrich_file(path: str, rel: str, nodes_in_file: list[dict]) -> None:
    """Call claude -p to fill summary/tags/complexity for all nodes in a file."""
    try:
        code = open(path, errors='ignore').read()
    except Exception:
        return
    lines = code.splitlines()
    if len(lines) > ENRICH_MAX_FILE_LINES:
        return  # skip very large files — too many tokens

    lang = EXT_LANG.get(Path(path).suffix, 'code')
    prompt = _ENRICH_PROMPT.format(lang=lang, path=rel, code=code[:6000])

    try:
        r = subprocess.run(
            ['claude', '-p', prompt,
             '--model', 'claude-haiku-4-5-20251001',
             '--output-format', 'json'],
            capture_output=True, text=True, timeout=60)
        raw = r.stdout.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # claude -p wraps in {"result": ...}
            outer = json.loads(raw)
            txt = outer.get('result', raw)
            # strip possible markdown fences
            txt = re.sub(r'^```[a-z]*\n?', '', txt.strip())
            txt = re.sub(r'\n?```$', '', txt.strip())
            data = json.loads(txt)
    except Exception:
        return

    fn_sums  = data.get('functionSummaries', {})
    cls_sums = data.get('classSummaries', {})
    file_sum = data.get('fileSummary', '')
    tags     = data.get('tags', [])
    cplx     = data.get('complexity', 'simple')

    for node in nodes_in_file:
        if node['type'] == 'file':
            node['summary'] = file_sum
            node['tags']    = tags
            node['complexity'] = cplx
        elif node['type'] == 'function':
            node['summary']    = fn_sums.get(node['name'], '')
            node['tags']       = tags  # file-level tags as fallback
            node['complexity'] = cplx
        elif node['type'] == 'class':
            node['summary']    = cls_sums.get(node['name'], '')
            node['tags']       = tags
            node['complexity'] = cplx


# ─── Graph build ─────────────────────────────────────────────────────────────

def build_graph(repo_path: str, enrich: bool = False) -> dict:
    repo  = Path(repo_path).resolve()
    nodes = []  # flat list of GraphNode dicts

    # ---- Phase 1: structure extraction ----
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, repo)
            if fname.endswith('.py'):
                file_nodes = extract_python(full, rel)
            elif fname.endswith('.go') and not fname.endswith('.pb.go'):
                file_nodes = extract_go(full, rel)
            elif fname.endswith(('.js', '.ts', '.jsx', '.tsx')):
                file_nodes = extract_js(full, rel)
            else:
                continue
            if file_nodes:
                nodes.extend(file_nodes)

    # ---- Phase 2: LLM enrichment (optional) ----
    if enrich:
        # Group nodes by filePath for batched per-file calls
        from collections import defaultdict
        by_file = defaultdict(list)
        for n in nodes:
            by_file[n['filePath']].append(n)

        total = len(by_file)
        for i, (rel_path, file_nodes) in enumerate(by_file.items(), 1):
            full_path = str(repo / rel_path)
            print(f"  Enriching {i}/{total}: {rel_path}", flush=True)
            _enrich_file(full_path, rel_path, file_nodes)

    # ---- Edges: import relationships (file→file) ----
    file_ids   = {n['filePath']: n['id'] for n in nodes if n['type'] == 'file'}
    path_stems = {Path(fp).stem: fid for fp, fid in file_ids.items()}
    edges = []

    # Collect imports from file source
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, repo)
            if rel not in file_ids:
                continue
            src_id = file_ids[rel]
            try:
                src = open(full, errors='ignore').read()
            except Exception:
                continue

            raw_imports = []
            if fname.endswith('.py'):
                try:
                    tree = ast.parse(src)
                    for n in ast.walk(tree):
                        if isinstance(n, ast.Import):
                            raw_imports += [a.name for a in n.names]
                        elif isinstance(n, ast.ImportFrom) and n.module:
                            raw_imports.append(n.module)
                except Exception:
                    pass
            elif fname.endswith('.go'):
                raw_imports += [m.group(1).split('/')[-1]
                                for m in re.finditer(r'"([^"]+)"', src)]
            elif fname.endswith(('.js', '.ts', '.jsx', '.tsx')):
                raw_imports += [m.group(1).split('/')[-1]
                                for m in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", src)]

            for imp in raw_imports:
                for part in [imp, imp.split('.')[-1]]:
                    target = path_stems.get(part) or file_ids.get(part + '.py')
                    if target and target != src_id:
                        edges.append({'source': src_id, 'target': target, 'type': 'imports'})
                        break

    # Edges: file contains function/class
    for n in nodes:
        if n['type'] in ('function', 'class'):
            parent_id = file_ids.get(n['filePath'])
            if parent_id:
                edges.append({'source': parent_id, 'target': n['id'], 'type': 'contains'})

    fn_count  = sum(1 for n in nodes if n['type'] == 'function')
    cls_count = sum(1 for n in nodes if n['type'] == 'class')
    fil_count = sum(1 for n in nodes if n['type'] == 'file')
    return {
        'version': '2',
        'repo': str(repo),
        'stats': {
            'files': fil_count, 'functions': fn_count,
            'classes': cls_count, 'edges': len(edges),
            'enriched': enrich,
        },
        'nodes': nodes,
        'edges': edges,
    }


# ─── Query ────────────────────────────────────────────────────────────────────

def _read_snippet(repo_root: str, file_path: str, line_range: list) -> str:
    if not line_range or len(line_range) < 2:
        return ''
    full = os.path.join(repo_root, file_path)
    if not os.path.exists(full):
        return ''
    try:
        src_lines = open(full, errors='ignore').readlines()
        s = max(0, line_range[0] - 1)
        e = min(len(src_lines), line_range[1])
        if e - s > MAX_SNIPPET:
            e = s + MAX_SNIPPET
        return ''.join(src_lines[s:e]).rstrip()
    except Exception:
        return ''


def query_graph(question: str, graph: dict, top_k: int = 3,
                repo_root: str = None) -> str:
    """Keyword RAG over the graph.

    Scores nodes by overlap of query tokens with name + signature + docstring + summary + tags.
    Returns rich context: summary + real code snippet (when repo_root available).
    Falls back to signature-only for old graph.json format (version < 2).
    """
    stopwords = {
        'what','how','why','does','the','a','an','is','in','to','of','for','and',
        'or','with','this','that','show','me','write','explain','get','use','make',
        'can','do','it','its','be','are','was','were','has','have','had','i',
        'return','returns','when','where','which','who',
    }
    q_tokens = set(re.findall(r'\w+', question.lower())) - stopwords
    if not q_tokens:
        return ''

    root = repo_root or graph.get('repo', '')

    # Support both v2 (flat node list) and v1 (file-centric nodes)
    version = graph.get('version', '1')

    if version == '2':
        return _query_v2(question, q_tokens, graph, top_k, root)
    else:
        return _query_v1(q_tokens, graph, top_k, root)


def _query_v2(question: str, q_tokens: set, graph: dict, top_k: int, root: str) -> str:
    """Query the v2 flat-node graph (our new format)."""
    scored = []
    for node in graph['nodes']:
        if node['type'] not in ('function', 'class'):
            continue
        text = ' '.join([
            node.get('name', ''),
            node.get('signature', ''),
            node.get('docstring', ''),
            node.get('summary', ''),
            ' '.join(node.get('tags', [])),
        ]).lower()
        tokens = set(re.findall(r'\w+', text))
        score  = len(q_tokens & tokens)
        if node['name'].lower() in q_tokens:
            score += 5
        if score > 0:
            scored.append((score, node))

    scored.sort(key=lambda x: -x[0])
    top = scored[:top_k]
    if not top:
        return ''

    lines = ['### Relevant codebase context:']
    for _, node in top:
        fp   = node.get('filePath', '')
        name = node.get('name', '')
        sig  = node.get('signature', '')
        doc  = node.get('docstring', '') or node.get('summary', '')
        lr   = node.get('lineRange')
        lang = EXT_LANG.get(Path(fp).suffix, '')

        lines.append(f"\n**{fp} — {name}**")
        if doc:
            lines.append(f"_{doc[:120]}_")

        snippet = _read_snippet(root, fp, lr) if root and lr else ''
        if snippet:
            lines.append(f"```{lang}")
            lines.extend(snippet.splitlines())
            lines.append("```")
        elif sig:
            lines.append(f"  {sig}")

    lines.append('')
    return '\n'.join(lines)


def _query_v1(q_tokens: set, graph: dict, top_k: int, root: str) -> str:
    """Query legacy v1 file-centric graph (backward compat)."""
    scored = []
    for node in graph['nodes']:
        fn_text  = ' '.join(f"{f['name']} {f['signature']} {f.get('docstring','')}" for f in node.get('functions', []))
        cls_text = ' '.join(f"{c['name']} {c.get('docstring','')}" for c in node.get('classes', []))
        full_text = f"{node['path']} {fn_text} {cls_text}".lower()
        score = len(q_tokens & set(re.findall(r'\w+', full_text)))
        for f in node.get('functions', []):
            if f['name'].lower() in q_tokens:
                score += 3
        if score > 0:
            scored.append((score, node))

    scored.sort(key=lambda x: -x[0])
    top = scored[:top_k]
    if not top:
        return ''

    lines = ['### Relevant codebase context (from graph index):']
    for _, node in top:
        lines.append(f"\n**{node['path']}**")
        for fn in node.get('functions', [])[:4]:
            ls = fn.get('line_start', fn.get('line', 0))
            le = fn.get('line_end', ls)
            snippet = _read_snippet(root, node['path'], [ls, le]) if root and ls else ''
            if snippet:
                ext  = Path(node['path']).suffix
                lang = EXT_LANG.get(ext, '')
                lines.append(f"  ```{lang}")
                for sl in snippet.splitlines()[:MAX_SNIPPET]:
                    lines.append(f"  {sl}")
                lines.append(f"  ```")
            else:
                doc = f"  # {fn.get('docstring','')[:80]}" if fn.get('docstring') else ''
                lines.append(f"  {fn['signature']}{doc}")
        for cls in node.get('classes', [])[:2]:
            lines.append(f"  class {cls['name']}")
    lines.append('')
    return '\n'.join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='RepoCoach graph builder / RAG query')
    parser.add_argument('--repo',      help='Path to target repo (build mode)')
    parser.add_argument('--out',       default=DEFAULT_GRAPH, help='Output graph.json path')
    parser.add_argument('--enrich',    action='store_true',
                        help='Call claude -p per file to generate summaries/tags/complexity')
    parser.add_argument('--query',     help='Question to find relevant context for (query mode)')
    parser.add_argument('--graph',     default=DEFAULT_GRAPH, help='Existing graph.json (query mode)')
    parser.add_argument('--repo-root', help='Repo root for fetching real code snippets (query mode)')
    parser.add_argument('--top-k',     type=int, default=5, help='Nodes to return per query')
    args = parser.parse_args()

    if args.query:
        if not os.path.exists(args.graph):
            print(f"❌ No graph at {args.graph} — run --repo first", file=sys.stderr)
            sys.exit(1)
        graph = json.load(open(args.graph))
        result = query_graph(args.query, graph, args.top_k, repo_root=args.repo_root)
        print(result or '(no relevant nodes found)')
        return

    if not args.repo:
        parser.print_help()
        sys.exit(1)
    if not os.path.isdir(args.repo):
        print(f"❌ Not a directory: {args.repo}", file=sys.stderr)
        sys.exit(1)

    print(f"Building graph for {args.repo}...")
    if args.enrich:
        print("LLM enrichment ON — will call claude -p per file (haiku, ~300 files)")
    graph = build_graph(args.repo, enrich=args.enrich)
    s = graph['stats']
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(graph, open(args.out, 'w'), indent=2)
    print(f"✅ {args.out}")
    print(f"   {s['files']} files · {s['functions']} fns · {s['classes']} classes · {s['edges']} edges")
    if args.enrich:
        print("   Summaries/tags/complexity enriched via LLM ✅")


if __name__ == '__main__':
    main()
