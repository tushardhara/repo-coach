#!/usr/bin/env python3
"""
graph_builder.py — RAG-ready codebase graph for RepoCoach

Builds a knowledge graph from the target repo (Python AST + Go/JS regex).
Nodes = files with functions/classes/imports. Edges = local import relationships.

Usage:
  # Build
  python3 scripts/graph_builder.py --repo ~/Promotions --out ~/finetune-workspace/graph.json

  # Query (returns context string for prompt injection)
  python3 scripts/graph_builder.py --query "how does session handling work"

  # Query with custom graph path
  python3 scripts/graph_builder.py --query "IngestToRedis" --graph ~/finetune-workspace/graph.json

v1: keyword search. v2 todo: embeddings (all-MiniLM-L6-v2, ~80MB, runs locally).
"""
import ast, os, json, re, sys, argparse
from pathlib import Path

SKIP_DIRS = {'node_modules', '.git', '__pycache__', 'dist', 'build', '.venv', 'venv', 'vendor'}
DEFAULT_GRAPH = os.path.expanduser('~/finetune-workspace/graph.json')


def extract_file(path: str, rel: str) -> dict | None:
    try:
        source = open(path, errors='ignore').read()
        tree = ast.parse(source)
    except SyntaxError:
        return None

    functions, classes, imports = [], [], []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ''
            args = [a.arg for a in node.args.args]
            functions.append({
                'name': node.name,
                'signature': f"def {node.name}({', '.join(args)})",
                'docstring': doc[:150],
                'line': node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ''
            bases = []
            try:
                bases = [ast.unparse(b) for b in node.bases]
            except Exception:
                pass
            classes.append({
                'name': node.name,
                'bases': bases,
                'docstring': doc[:150],
                'line': node.lineno,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    # Build search text (not stored in graph — built at query time from node fields)
    return {
        'id': f"file:{rel}",
        'path': rel,
        'functions': functions[:50],
        'classes': classes[:20],
        'imports': list(dict.fromkeys(imports))[:30],  # dedup, preserve order
    }


def extract_go_file(path: str, rel: str) -> dict | None:
    try:
        src = open(path, errors='ignore').read()
    except Exception:
        return None

    functions, classes, imports = [], [], []

    # Functions: func (recv *Type) Name(params) ReturnType
    for m in re.finditer(r'^func\s+(?:\([^)]*\)\s+)?(\w+)\s*(\([^)]*\))', src, re.MULTILINE):
        functions.append({
            'name': m.group(1),
            'signature': m.group(0)[:120].replace('\n', ' '),
            'docstring': '',
            'line': src[:m.start()].count('\n') + 1,
        })

    # Structs and interfaces
    for m in re.finditer(r'^type\s+(\w+)\s+(struct|interface)\b', src, re.MULTILINE):
        classes.append({'name': m.group(1), 'bases': [m.group(2)], 'docstring': ''})

    # Imports: single-line and block
    for m in re.finditer(r'^import\s+"([^"]+)"', src, re.MULTILINE):
        imports.append(m.group(1).split('/')[-1])
    for m in re.finditer(r'^import\s*\(([^)]+)\)', src, re.MULTILINE | re.DOTALL):
        for pkg in re.findall(r'"([^"]+)"', m.group(1)):
            imports.append(pkg.split('/')[-1])

    if not functions and not classes:
        return None
    return {
        'id': f"file:{rel}",
        'path': rel,
        'functions': functions[:50],
        'classes': classes[:20],
        'imports': list(dict.fromkeys(imports))[:30],
    }


def extract_js_file(path: str, rel: str) -> dict | None:
    try:
        src = open(path, errors='ignore').read()
    except Exception:
        return None

    functions, classes, imports = [], [], []

    # Named functions and arrow functions assigned to const/let
    for m in re.finditer(r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(\([^)]*\))', src, re.MULTILINE):
        functions.append({'name': m.group(1), 'signature': m.group(0)[:120], 'docstring': '', 'line': src[:m.start()].count('\n') + 1})
    for m in re.finditer(r'^(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\(', src, re.MULTILINE):
        functions.append({'name': m.group(1), 'signature': m.group(0)[:80], 'docstring': '', 'line': src[:m.start()].count('\n') + 1})

    # Classes
    for m in re.finditer(r'^(?:export\s+)?class\s+(\w+)', src, re.MULTILINE):
        classes.append({'name': m.group(1), 'bases': [], 'docstring': ''})

    # Imports: require / ES import
    for m in re.finditer(r"require\(['\"]([^'\"]+)['\"]\)", src):
        imports.append(m.group(1).split('/')[-1])
    for m in re.finditer(r"^import\s+.*?from\s+['\"]([^'\"]+)['\"]", src, re.MULTILINE):
        imports.append(m.group(1).split('/')[-1])

    if not functions and not classes:
        return None
    return {
        'id': f"file:{rel}",
        'path': rel,
        'functions': functions[:50],
        'classes': classes[:20],
        'imports': list(dict.fromkeys(imports))[:30],
    }


def build_graph(repo_path: str) -> dict:
    repo = Path(repo_path).resolve()
    nodes = []

    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, repo)
            if fname.endswith('.py'):
                node = extract_file(full, rel)
            elif fname.endswith('.go') and not fname.endswith('.pb.go'):
                node = extract_go_file(full, rel)
            elif fname.endswith(('.js', '.ts', '.jsx', '.tsx')):
                node = extract_js_file(full, rel)
            else:
                continue
            if node:
                nodes.append(node)

    # Build import edges: resolve local imports to nodes in this repo
    path_stems = {Path(n['path']).stem: n['id'] for n in nodes}
    path_map   = {n['path']: n['id'] for n in nodes}
    edges = []
    for node in nodes:
        for imp in node['imports']:
            parts = imp.split('.')
            # Try longest-suffix match
            for length in range(len(parts), 0, -1):
                key = '.'.join(parts[-length:])
                target = path_stems.get(key) or path_map.get(key + '.py')
                if target and target != node['id']:
                    edges.append({'source': node['id'], 'target': target, 'type': 'imports'})
                    break

    total_fns = sum(len(n['functions']) for n in nodes)
    total_cls = sum(len(n['classes']) for n in nodes)
    return {
        'repo': str(repo),
        'stats': {'files': len(nodes), 'functions': total_fns, 'classes': total_cls, 'edges': len(edges)},
        'nodes': nodes,
        'edges': edges,
    }


def query_graph(question: str, graph: dict, top_k: int = 5) -> str:
    """Keyword RAG: return top-k nodes as a prompt-ready context string."""
    stopwords = {
        'what','how','why','does','the','a','an','is','in','to','of','for','and',
        'or','with','this','that','show','me','write','explain','get','use','make',
        'can','do','it','its','be','are','was','were','has','have','had','i',
        'return','returns','when','where','which','who',
    }
    q_tokens = set(re.findall(r'\w+', question.lower())) - stopwords
    if not q_tokens:
        return ''

    scored = []
    for node in graph['nodes']:
        # Build search text lazily
        fn_text  = ' '.join(f"{f['name']} {f['signature']} {f['docstring']}" for f in node['functions'])
        cls_text = ' '.join(f"{c['name']} {c['docstring']}" for c in node['classes'])
        full_text = f"{node['path']} {fn_text} {cls_text}".lower()
        node_tokens = set(re.findall(r'\w+', full_text))

        score = len(q_tokens & node_tokens)
        # Bonus: exact name match in functions/classes
        for f in node['functions']:
            if f['name'].lower() in q_tokens:
                score += 3
        for c in node['classes']:
            if c['name'].lower() in q_tokens:
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
        for fn in node['functions'][:6]:
            doc = f"  # {fn['docstring'][:80]}" if fn['docstring'] else ''
            lines.append(f"  {fn['signature']}{doc}")
        for cls in node['classes'][:3]:
            bases = f"({', '.join(cls['bases'])})" if cls['bases'] else ''
            doc = f"  # {cls['docstring'][:80]}" if cls['docstring'] else ''
            lines.append(f"  class {cls['name']}{bases}{doc}")
    lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='RepoCoach graph builder / RAG query')
    parser.add_argument('--repo',  help='Path to target repo (build mode)')
    parser.add_argument('--out',   default=DEFAULT_GRAPH, help='Output graph.json path')
    parser.add_argument('--query', help='Question to find relevant context for (query mode)')
    parser.add_argument('--graph', default=DEFAULT_GRAPH, help='Existing graph.json path (query mode)')
    parser.add_argument('--top-k', type=int, default=5, help='Nodes to return per query')
    args = parser.parse_args()

    if args.query:
        if not os.path.exists(args.graph):
            print(f"❌ No graph at {args.graph} — run --repo first", file=sys.stderr)
            sys.exit(1)
        graph = json.load(open(args.graph))
        print(query_graph(args.query, graph, args.top_k) or '(no relevant nodes found)')
        return

    if not args.repo:
        parser.print_help()
        sys.exit(1)

    if not os.path.isdir(args.repo):
        print(f"❌ Not a directory: {args.repo}", file=sys.stderr)
        sys.exit(1)

    print(f"Building graph for {args.repo}...")
    graph = build_graph(args.repo)
    s = graph['stats']
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    json.dump(graph, open(args.out, 'w'), indent=2)
    print(f"✅ {args.out}")
    print(f"   {s['files']} files · {s['functions']} functions · {s['classes']} classes · {s['edges']} import edges")


if __name__ == '__main__':
    main()
