"""Tree-sitter powered structural analysis.

Rather than writing a query file per language we drive extraction off small
node-type maps. That keeps adding a new language to ~4 lines and avoids
breaking whenever a grammar bumps its query syntax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.logging_config import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------- node maps
FUNCTION_NODES: dict[str, set[str]] = {
    "python": {"function_definition"},
    "javascript": {"function_declaration", "function_expression", "method_definition", "arrow_function"},
    "typescript": {"function_declaration", "function_expression", "method_definition", "arrow_function", "method_signature"},
    "tsx": {"function_declaration", "function_expression", "method_definition", "arrow_function"},
    "java": {"method_declaration", "constructor_declaration"},
    "go": {"function_declaration", "method_declaration"},
    "ruby": {"method", "singleton_method"},
    "php": {"function_definition", "method_declaration"},
    "rust": {"function_item"},
    "c": {"function_definition"},
    "cpp": {"function_definition"},
    "c_sharp": {"method_declaration", "constructor_declaration"},
    "kotlin": {"function_declaration"},
}

CLASS_NODES: dict[str, set[str]] = {
    "python": {"class_definition"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration", "interface_declaration"},
    "tsx": {"class_declaration"},
    "java": {"class_declaration", "interface_declaration", "enum_declaration"},
    "go": {"type_declaration"},
    "ruby": {"class", "module"},
    "php": {"class_declaration", "interface_declaration"},
    "rust": {"struct_item", "impl_item", "trait_item"},
    "cpp": {"class_specifier", "struct_specifier"},
    "c_sharp": {"class_declaration", "interface_declaration"},
    "kotlin": {"class_declaration", "object_declaration"},
}

CALL_NODES = {
    "call", "call_expression", "method_invocation", "function_call_expression",
    "invocation_expression", "new_expression", "macro_invocation",
}

IMPORT_NODES = {
    "import_statement", "import_from_statement", "import_declaration",
    "import_spec", "use_declaration", "namespace_use_declaration",
    "require_once_statement", "include_statement", "using_directive",
    "package_import", "import_header",
}

BRANCH_NODES = {
    "if_statement", "for_statement", "while_statement", "case", "catch_clause",
    "conditional_expression", "elif_clause", "else_clause", "switch_statement",
    "try_statement", "except_clause", "ternary_expression", "boolean_operator",
    "for_in_statement", "do_statement", "match_statement",
}


@dataclass
class ParsedSymbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    parent: str | None = None
    complexity: int = 1
    source: str = ""


@dataclass
class ParsedCall:
    caller: str
    callee: str
    line: int


@dataclass
class ParsedImport:
    target: str
    line: int
    is_external: bool = False


@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    error: str | None = None


@lru_cache(maxsize=32)
def _get_parser(language: str):
    from tree_sitter_language_pack import get_parser

    return get_parser(language)  # raises LookupError for unsupported grammars


def _text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _node_name(node, src: bytes) -> str | None:
    for fname in ("name", "declarator", "field", "pattern"):
        child = node.child_by_field_name(fname)
        if child is not None:
            txt = _text(child, src).strip()
            # C-style declarators: `foo(int a)` -> `foo`
            return txt.split("(")[0].strip().lstrip("*") or None
    for child in node.named_children:
        if child.type in ("identifier", "type_identifier", "field_identifier",
                          "property_identifier", "constant", "word"):
            return _text(child, src)
    return None


def _callee_name(node, src: bytes) -> str | None:
    fn = node.child_by_field_name("function") or node.child_by_field_name("constructor")
    target = fn if fn is not None else (node.named_children[0] if node.named_children else None)
    if target is None:
        return None
    raw = _text(target, src).strip()
    if not raw or len(raw) > 200 or "\n" in raw:
        return None
    # a.b.c(...) -> c   |  obj->m() -> m
    for sep in ("::", "->", "."):
        if sep in raw:
            raw = raw.split(sep)[-1]
    return raw.strip() or None


def _complexity(node) -> int:
    score = 1
    stack = [node]
    while stack:
        cur = stack.pop()
        for child in cur.children:
            if child.type in BRANCH_NODES:
                score += 1
            stack.append(child)
    return score


def _signature(node, src: bytes, max_len: int = 220) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else min(node.end_byte, node.start_byte + max_len)
    sig = src[node.start_byte : end].decode("utf-8", errors="ignore").strip()
    sig = " ".join(sig.split())
    return sig[:max_len]


def _import_targets(node, src: bytes, language: str) -> list[str]:
    raw = _text(node, src)
    targets: list[str] = []
    if language == "python":
        mod = node.child_by_field_name("module_name")
        if mod is not None:
            targets.append(_text(mod, src))
        else:
            for child in node.named_children:
                if child.type in ("dotted_name", "aliased_import", "relative_import"):
                    targets.append(_text(child, src).split(" as ")[0])
    else:
        for child in node.named_children:
            if child.type in ("string", "string_literal", "interpreted_string_literal", "scoped_identifier"):
                targets.append(_text(child, src).strip("\"'`"))
    if not targets:
        cleaned = " ".join(raw.split())[:160]
        targets.append(cleaned)
    return [t for t in (x.strip() for x in targets) if t]


def _is_external(target: str, language: str) -> bool:
    if language in ("javascript", "typescript", "tsx"):
        return not target.startswith((".", "/", "@/", "~"))
    if language == "python":
        return not target.startswith(".")
    return "/" not in target or target.startswith(("github.com", "golang.org"))


def parse_source(path: str, language: str, source: str) -> ParsedFile:
    """Extract symbols, call edges and imports from one file."""
    result = ParsedFile(path=path, language=language)
    try:
        parser = _get_parser(language)
    except Exception as exc:  # unsupported grammar - degrade, never crash
        result.error = f"no grammar: {exc}"
        return result

    src = source.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(src)
    except Exception as exc:
        result.error = f"parse failed: {exc}"
        return result

    fn_types = FUNCTION_NODES.get(language, set())
    cls_types = CLASS_NODES.get(language, set())
    module = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    # walk with an explicit stack so we can track the enclosing scope name
    stack: list[tuple[Any, str | None, str]] = [(tree.root_node, None, module)]
    while stack:
        node, parent_name, scope = stack.pop()
        next_parent, next_scope = parent_name, scope

        if node.type in cls_types or node.type in fn_types:
            name = _node_name(node, src)
            if name:
                is_class = node.type in cls_types
                kind = "class" if is_class else ("method" if parent_name else "function")
                qualified = f"{scope}.{name}" if scope else name
                result.symbols.append(
                    ParsedSymbol(
                        name=name,
                        qualified_name=qualified,
                        kind=kind,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=_signature(node, src),
                        parent=parent_name,
                        complexity=_complexity(node),
                        source=_text(node, src),
                    )
                )
                next_parent = name
                next_scope = qualified

        elif node.type in CALL_NODES:
            callee = _callee_name(node, src)
            if callee:
                result.calls.append(
                    ParsedCall(
                        caller=scope or module,
                        callee=callee,
                        line=node.start_point[0] + 1,
                    )
                )

        elif node.type in IMPORT_NODES:
            for target in _import_targets(node, src, language):
                result.imports.append(
                    ParsedImport(
                        target=target,
                        line=node.start_point[0] + 1,
                        is_external=_is_external(target, language),
                    )
                )

        for child in reversed(node.children):
            stack.append((child, next_parent, next_scope))

    return result
