"""Question classifier and first-tool suggester."""
import re
from typing import Tuple

STRATEGIES = ["flow", "impact", "table", "symbol", "general"]

# Each list is ordered: checked in order, first match wins within the group.
# Single-word entries are matched with word boundaries to avoid false positives
# inside identifiers (e.g. "assign" should not fire on "AssignVoucher").
_FLOW_PHRASES    = ["how does", "walk through", "trace through"]
_FLOW_WORDS      = ["flow", "trace", "walk"]

_IMPACT_PHRASES  = ["who calls", "callers of", "callers"]
_IMPACT_WORDS    = ["impact", "affect", "breaks"]

# Table keywords checked before route/path/flow single-words so "reads from"
# and "writes to" phrases take priority.
_TABLE_PHRASES   = ["reads from", "writes to", "reads table", "writes table"]
_TABLE_WORDS     = ["table", "tables", "database", "sql"]
# "db" matched as word only — avoid false hits in identifiers
_TABLE_WORDS_WB  = ["db"]

_REDIS_WORDS     = ["redis", "queue", "kafka", "rabbitmq", "pubsub", "celery", "worker", "broker"]
_QUEUE_PHRASES   = ["reads from redis", "writes to redis", "publishes to", "consumes from"]

_SYMBOL_PHRASES  = ["what does", "what is"]
_SYMBOL_WORDS    = ["function", "method", "class", "explain"]

# Route/path as flow only when not overridden by table/impact already
_FLOW_WORDS2     = ["route", "path", "endpoint"]

# Regex to extract a candidate table name from table-strategy questions
_TABLE_RE = re.compile(
    r'\b(?:table|from|into|update|select\s+\S+\s+from)\s+[`"\']?(\w+)[`"\']?',
    re.IGNORECASE,
)
# Regex to pull a likely identifier from the question
_IDENT_RE = re.compile(r'\b([A-Z][a-zA-Z0-9_]{2,}|[a-z_][a-zA-Z0-9_]{3,})\b')


def _has_phrase(q: str, phrases: list) -> bool:
    return any(p in q for p in phrases)


def _has_word(q: str, words: list) -> bool:
    """Word-boundary match."""
    return any(bool(re.search(r'\b' + re.escape(w) + r'\b', q)) for w in words)


def classify_question(question: str) -> str:
    """
    Returns one of STRATEGIES based on keyword matching.
    Phrase matches checked before single-word to avoid identifier false positives.
    Priority ordering within each category: phrase > word.
    Overall priority: table-phrase > impact-phrase > symbol-phrase >
                      table-word > impact-word > symbol-word > flow > general.
    """
    q = question.lower()

    # Redis/queue detection before table check — prevents misroute to search_table
    if _has_phrase(q, _QUEUE_PHRASES):
        return "general"
    if _has_word(q, _REDIS_WORDS):
        return "general"

    # Phrase-level checks first (more specific)
    if _has_phrase(q, _TABLE_PHRASES):
        return "table"
    if _has_phrase(q, _IMPACT_PHRASES):
        return "impact"
    if _has_phrase(q, _SYMBOL_PHRASES):
        return "symbol"
    if _has_phrase(q, _FLOW_PHRASES):
        return "flow"

    # Word-boundary checks
    if _has_word(q, _TABLE_WORDS) or _has_word(q, _TABLE_WORDS_WB):
        return "table"
    if _has_word(q, _IMPACT_WORDS):
        return "impact"
    # Flow core words beat "explain" (e.g. "explain the voucher assignment flow")
    if _has_word(q, _FLOW_WORDS) or _has_word(q, _FLOW_WORDS2):
        return "flow"
    if _has_word(q, _SYMBOL_WORDS):
        return "symbol"

    return "general"


def _extract_table_name(question: str) -> str:
    """Try to extract a table name from a question."""
    m = _TABLE_RE.search(question)
    if m:
        return m.group(1)
    # Fallback: grab the last capitalised or snake_case word
    tokens = question.split()
    for tok in reversed(tokens):
        clean = re.sub(r'[^a-zA-Z0-9_]', '', tok)
        if len(clean) >= 3:
            return clean
    return question.strip()


_STOPWORDS = {
    "what", "does", "how", "who", "where", "when", "why", "which", "is", "are",
    "the", "this", "that", "these", "those", "and", "for", "from", "with",
    "explain", "tell", "show", "find", "get", "give", "list", "describe",
    "function", "method", "class", "module", "package", "file", "route",
    "table", "database", "redis", "queue", "event", "symbol", "code",
    "can", "will", "would", "should", "could", "call", "calls", "use", "used",
}


def _extract_identifier(question: str) -> str:
    """Extract likely function/class/table name from question, skipping stopwords."""
    matches = _IDENT_RE.findall(question)
    # Filter stopwords
    matches = [m for m in matches if m.lower() not in _STOPWORDS]
    # Prefer CamelCase (likely a symbol name)
    camel = [m for m in matches if m[0].isupper()]
    if camel:
        return camel[0]
    if matches:
        return matches[0]
    # Fallback: last meaningful word in the question
    words = question.split()
    for w in reversed(words):
        clean = w.strip("?.,!").lower()
        if clean and clean not in _STOPWORDS and len(clean) >= 3:
            return w.strip("?.,!")
    return question.strip()


_STEM_MAP = {
    "assignment": "assign", "assignments": "assign",
    "creation": "create", "deletion": "delete",
    "validation": "validate", "authentication": "auth",
    "authorization": "auth", "registration": "register",
    "processing": "process", "handling": "handle",
    "updating": "update", "fetching": "fetch",
    "listing": "list", "searching": "search",
}


def _extract_keywords(question: str) -> str:
    """Extract best search query from a question.
    Applies light stemming for nominalizations (assignment→assign).
    Returns the most code-like token."""
    # Apply stemming to lowercase words
    words = question.split()
    stemmed = []
    for w in words:
        clean = w.strip("?.,!").lower()
        stemmed.append(_STEM_MAP.get(clean, clean))

    # Re-run identifier extraction on the stemmed version
    stemmed_q = " ".join(stemmed)
    return _extract_identifier(stemmed_q) or _extract_identifier(question)


def suggest_first_tool(question: str, strategy: str) -> Tuple[str, dict]:
    """
    Suggest (tool_name, args) based on strategy.
    """
    q = question.lower()

    _ROUTE_WORDS = {"route", "endpoint", "api", "path", "http", "post", "get",
                    "put", "patch", "delete", "/"}

    if strategy == "flow":
        return "find_files", {"query": question, "top": 5}

    elif strategy == "impact":
        return "find_symbols", {"query": _extract_identifier(question)}

    elif strategy == "table":
        return "search_table", {"table_name": _extract_table_name(question)}

    elif strategy == "symbol":
        return "find_files", {"query": question, "top": 5}

    else:  # general
        return "find_files", {"query": question, "top": 5}
