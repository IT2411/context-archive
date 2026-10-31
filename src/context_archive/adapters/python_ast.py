"""Zero-execution Python AST analyzer for modules, symbols, imports, calls, and tests."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from context_archive.adapters.base import AdapterExtractionResult
from context_archive.model.graph import Diagnostic, Edge, Node, NodeKind
from context_archive.model.ids import (
    make_edge_id,
    make_file_id,
    make_module_id,
    make_symbol_id,
    normalize_posix_path,
)
from context_archive.model.provenance import Provenance

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.scanner.report import ScannedFile

EXTRACTOR_ID = "python_ast:1.0"
_SENTINEL_PATTERN = re.compile(r"<!--\s*CTXA:[^>]*-->", re.IGNORECASE)
_DYNAMIC_CALL_NAMES = frozenset({"eval", "exec", "getattr", "import_module", "__import__"})
_CONSTANT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def sanitize_docstring_summary(raw_doc: str | None) -> str:
    """Extract first paragraph of a docstring and neutralize CTXA sentinel injection."""
    if not raw_doc:
        return ""
    sanitized = _SENTINEL_PATTERN.sub("[CTXA-MARKER-SANITIZED]", raw_doc)
    paragraphs: list[str] = []
    current: list[str] = []
    for line in sanitized.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                break
        else:
            current.append(stripped)
    if current and not paragraphs:
        paragraphs.append(" ".join(current))
    summary = paragraphs[0] if paragraphs else ""
    return summary[:300]


def compute_python_module_name(rel_posix: str) -> str:
    """Derive dotted Python module name from a relative POSIX path (supporting src/ layout)."""
    norm = normalize_posix_path(rel_posix)
    parts = list(PurePosixPath(norm).parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]

    if not parts:
        return "root"

    last = parts[-1]
    stem = PurePosixPath(last).stem
    parts[-1] = stem

    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]

    return ".".join(parts)


def resolve_relative_module(current_rel_posix: str, module: str | None, level: int) -> str:
    """Resolve a relative `from ..pkg import x` import against the current file's package."""
    norm = normalize_posix_path(current_rel_posix)
    parts = list(PurePosixPath(norm).parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]

    pkg_parts = parts[:-1]
    up_steps = max(0, level - 1)
    pkg_parts = pkg_parts[: len(pkg_parts) - up_steps] if up_steps <= len(pkg_parts) else []

    if module:
        pkg_parts.extend(module.split("."))
    return ".".join(pkg_parts)


def _unparse_expr(node: ast.AST | None) -> str:
    """Safely unparse an AST expression node to string."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return "<expr>"


def format_function_signature(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Format a deterministic Python function/method signature string."""
    args = func_node.args
    formatted_params: list[str] = []

    pos_args = list(args.posonlyargs) + list(args.args)
    num_defaults = len(args.defaults)
    default_offset = len(pos_args) - num_defaults

    for idx, arg in enumerate(pos_args):
        param_str = arg.arg
        if arg.annotation is not None:
            param_str += f": {_unparse_expr(arg.annotation)}"
        if idx >= default_offset:
            default_node = args.defaults[idx - default_offset]
            param_str += f" = {_unparse_expr(default_node)}"
        formatted_params.append(param_str)
        if args.posonlyargs and idx == len(args.posonlyargs) - 1:
            formatted_params.append("/")

    if args.vararg is not None:
        vararg_str = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            vararg_str += f": {_unparse_expr(args.vararg.annotation)}"
        formatted_params.append(vararg_str)
    elif args.kwonlyargs:
        formatted_params.append("*")

    for kw_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
        kw_str = kw_arg.arg
        if kw_arg.annotation is not None:
            kw_str += f": {_unparse_expr(kw_arg.annotation)}"
        if kw_default is not None:
            kw_str += f" = {_unparse_expr(kw_default)}"
        formatted_params.append(kw_str)

    if args.kwarg is not None:
        kwarg_str = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            kwarg_str += f": {_unparse_expr(args.kwarg.annotation)}"
        formatted_params.append(kwarg_str)

    sig = f"({', '.join(formatted_params)})"
    if func_node.returns is not None:
        sig += f" -> {_unparse_expr(func_node.returns)}"
    return sig


@dataclass
class _CallSiteRecord:
    """Pending call reference inside a symbol or module body."""

    caller_id: str
    callee_name: str
    line_start: int
    line_end: int


@dataclass
class _BaseClassRecord:
    """Pending class inheritance reference."""

    class_id: str
    base_name: str
    line_start: int
    line_end: int


@dataclass
class _ParsedModuleInfo:
    """Intermediate AST representation of a single parsed Python file."""

    rel_posix: str
    is_test_file: bool
    module_name: str
    module_id: str
    file_id: str
    line_count: int
    symbols_by_short_name: dict[str, str] = field(default_factory=dict)
    symbols_by_qual_suffix: dict[str, str] = field(default_factory=dict)
    import_bindings: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    call_sites: list[_CallSiteRecord] = field(default_factory=list)
    base_records: list[_BaseClassRecord] = field(default_factory=list)
    test_symbol_ids: list[str] = field(default_factory=list)


def _extract_call_name(call_func: ast.expr) -> str | None:
    """Extract simple or dotted call target name (`foo` or `mod.foo`)."""
    if isinstance(call_func, ast.Name):
        return call_func.id
    if isinstance(call_func, ast.Attribute):
        if isinstance(call_func.value, ast.Name):
            return f"{call_func.value.id}.{call_func.attr}"
        return call_func.attr
    return None


def _collect_calls_in_body(
    statements: list[ast.stmt],
    *,
    caller_id: str,
    rel_posix: str,
    call_sites: list[_CallSiteRecord],
    diagnostics: list[Diagnostic],
) -> None:
    """Walk statement expressions (without descending into nested class/def scopes) for calls."""
    stack: list[ast.AST] = list(reversed(statements))
    while stack:
        current = stack.pop()
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if isinstance(current, ast.Call):
            callee = _extract_call_name(current.func)
            line_start = getattr(current, "lineno", 1)
            line_end = getattr(current, "end_lineno", line_start) or line_start
            if callee is not None:
                short_callee = callee.split(".")[-1]
                if short_callee in _DYNAMIC_CALL_NAMES:
                    diagnostics.append(
                        Diagnostic(
                            code="unresolved_dynamic_call",
                            severity="info",
                            message=f"Dynamic invocation '{callee}' cannot be statically resolved.",
                            source_path=rel_posix,
                            line=line_start,
                        )
                    )
                else:
                    call_sites.append(
                        _CallSiteRecord(
                            caller_id=caller_id,
                            callee_name=callee,
                            line_start=line_start,
                            line_end=line_end,
                        )
                    )
        for child in ast.iter_child_nodes(current):
            stack.append(child)


class PythonAstAdapter:
    """Deterministic Python AST analyzer implementing LanguageAdapter."""

    @property
    def adapter_id(self) -> str:
        return EXTRACTOR_ID

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        return scanned_file.language == "python" and scanned_file.category in (
            "source_code",
            "test",
        )

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
    ) -> AdapterExtractionResult:
        """Parse all Python files and link intra-repository symbols, imports, calls, and tests."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        diagnostics: list[Diagnostic] = []
        parsed_modules: dict[str, _ParsedModuleInfo] = {}
        global_symbols: dict[str, str] = {}

        python_files = sorted(
            (f for f in files if self.can_handle(f)),
            key=lambda item: item.path,
        )

        # Pass 1: Parse ASTs and extract File, Module, Class, Function, Method, Variable, Test nodes
        for scanned in python_files:
            rel_posix = normalize_posix_path(scanned.path)
            abs_path = repo_root / rel_posix
            try:
                source_text = abs_path.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover
                diagnostics.append(
                    Diagnostic(
                        code="file_read_error",
                        severity="warning",
                        message=f"Unable to read Python source: {exc}",
                        source_path=rel_posix,
                    )
                )
                continue

            try:
                tree = ast.parse(source_text, filename=rel_posix)
            except (SyntaxError, ValueError) as exc:
                err_line = getattr(exc, "lineno", 1) or 1
                diagnostics.append(
                    Diagnostic(
                        code="python_syntax_error",
                        severity="warning",
                        message=f"SyntaxError while parsing Python file: {exc}",
                        source_path=rel_posix,
                        line=err_line,
                    )
                )
                continue

            lines = source_text.splitlines()
            line_count = max(1, len(lines))
            file_id = make_file_id(rel_posix)
            module_name = compute_python_module_name(rel_posix)
            module_id = make_module_id("py", rel_posix, module_name)
            is_test_file = scanned.category == "test"

            file_prov = Provenance(
                source_path=rel_posix,
                line_start=1,
                line_end=line_count,
                extractor=EXTRACTOR_ID,
                evidence_kind="deterministic",
                confidence="high",
            )
            nodes.append(
                Node(
                    id=file_id,
                    kind="File",
                    name=PurePosixPath(rel_posix).name,
                    qualified_name=rel_posix,
                    attributes={"language": "python", "size_bytes": scanned.size_bytes},
                    provenance=file_prov,
                )
            )

            mod_doc = sanitize_docstring_summary(ast.get_docstring(tree))
            nodes.append(
                Node(
                    id=module_id,
                    kind="Module",
                    name=module_name.split(".")[-1],
                    qualified_name=module_name,
                    attributes={"docstring_summary": mod_doc, "is_test_module": is_test_file},
                    provenance=file_prov,
                )
            )
            edges.append(
                Edge(
                    id=make_edge_id("CONTAINS", file_id, module_id),
                    kind="CONTAINS",
                    source_id=file_id,
                    target_id=module_id,
                    provenance=file_prov,
                )
            )

            mod_info = _ParsedModuleInfo(
                rel_posix=rel_posix,
                is_test_file=is_test_file,
                module_name=module_name,
                module_id=module_id,
                file_id=file_id,
                line_count=line_count,
            )
            parsed_modules[module_name] = mod_info

            self._visit_scope(
                statements=tree.body,
                parent_id=module_id,
                qual_prefix="",
                mod_info=mod_info,
                nodes=nodes,
                edges=edges,
                diagnostics=diagnostics,
                global_symbols=global_symbols,
                in_class=False,
            )

            _collect_calls_in_body(
                tree.body,
                caller_id=module_id,
                rel_posix=rel_posix,
                call_sites=mod_info.call_sites,
                diagnostics=diagnostics,
            )

        # Pass 2: Resolve intra-repository IMPORTS, INHERITS, CALLS, and TESTED_BY edges
        self._link_relationships(
            parsed_modules=parsed_modules,
            global_symbols=global_symbols,
            edges=edges,
        )

        return AdapterExtractionResult(
            nodes=tuple(nodes),
            edges=tuple(edges),
            diagnostics=tuple(diagnostics),
        )

    def _visit_scope(
        self,
        *,
        statements: list[ast.stmt],
        parent_id: str,
        qual_prefix: str,
        mod_info: _ParsedModuleInfo,
        nodes: list[Node],
        edges: list[Edge],
        diagnostics: list[Diagnostic],
        global_symbols: dict[str, str],
        in_class: bool,
    ) -> None:
        for stmt in statements:
            if isinstance(stmt, ast.Import):
                line_start = getattr(stmt, "lineno", 1)
                line_end = getattr(stmt, "end_lineno", line_start) or line_start
                for alias in stmt.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    mod_info.import_bindings[bound] = (alias.name, line_start, line_end)

            elif isinstance(stmt, ast.ImportFrom):
                line_start = getattr(stmt, "lineno", 1)
                line_end = getattr(stmt, "end_lineno", line_start) or line_start
                base_mod = (
                    resolve_relative_module(mod_info.rel_posix, stmt.module, stmt.level)
                    if stmt.level > 0
                    else (stmt.module or "")
                )
                for alias in stmt.names:
                    if alias.name == "*":
                        diagnostics.append(
                            Diagnostic(
                                code="wildcard_import",
                                severity="info",
                                message=f"Wildcard import from '{base_mod}' limits static linking.",
                                source_path=mod_info.rel_posix,
                                line=line_start,
                            )
                        )
                        continue
                    bound = alias.asname or alias.name
                    target_qual = f"{base_mod}.{alias.name}" if base_mod else alias.name
                    mod_info.import_bindings[bound] = (target_qual, line_start, line_end)

            elif isinstance(stmt, ast.ClassDef):
                self._extract_class(
                    stmt=stmt,
                    parent_id=parent_id,
                    qual_prefix=qual_prefix,
                    mod_info=mod_info,
                    nodes=nodes,
                    edges=edges,
                    diagnostics=diagnostics,
                    global_symbols=global_symbols,
                )

            elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                self._extract_function(
                    stmt=stmt,
                    parent_id=parent_id,
                    qual_prefix=qual_prefix,
                    mod_info=mod_info,
                    nodes=nodes,
                    edges=edges,
                    diagnostics=diagnostics,
                    global_symbols=global_symbols,
                    in_class=in_class,
                )

            elif not in_class and isinstance(stmt, ast.Assign | ast.AnnAssign):
                self._extract_module_constant(
                    stmt=stmt,
                    parent_id=parent_id,
                    mod_info=mod_info,
                    nodes=nodes,
                    edges=edges,
                    global_symbols=global_symbols,
                )

    def _extract_class(
        self,
        *,
        stmt: ast.ClassDef,
        parent_id: str,
        qual_prefix: str,
        mod_info: _ParsedModuleInfo,
        nodes: list[Node],
        edges: list[Edge],
        diagnostics: list[Diagnostic],
        global_symbols: dict[str, str],
    ) -> None:
        local_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
        full_qual = f"{mod_info.module_name}.{local_qual}"
        sym_id = make_symbol_id("py", mod_info.rel_posix, local_qual)
        line_start = getattr(stmt, "lineno", 1)
        line_end = getattr(stmt, "end_lineno", line_start) or line_start

        decorators = [_unparse_expr(dec) for dec in stmt.decorator_list]
        bases = [_unparse_expr(base) for base in stmt.bases]
        doc_summary = sanitize_docstring_summary(ast.get_docstring(stmt))

        prov = Provenance(
            source_path=mod_info.rel_posix,
            line_start=line_start,
            line_end=line_end,
            extractor=EXTRACTOR_ID,
            evidence_kind="deterministic",
            confidence="high",
        )
        nodes.append(
            Node(
                id=sym_id,
                kind="Class",
                name=stmt.name,
                qualified_name=full_qual,
                attributes={
                    "bases": bases,
                    "decorators": decorators,
                    "docstring_summary": doc_summary,
                },
                provenance=prov,
            )
        )
        edges.append(
            Edge(
                id=make_edge_id("DEFINES", parent_id, sym_id),
                kind="DEFINES",
                source_id=parent_id,
                target_id=sym_id,
                provenance=prov,
            )
        )

        mod_info.symbols_by_short_name.setdefault(stmt.name, sym_id)
        mod_info.symbols_by_qual_suffix[local_qual] = sym_id
        global_symbols[full_qual] = sym_id

        for base_expr in stmt.bases:
            base_name = _extract_call_name(base_expr)
            if base_name:
                mod_info.base_records.append(
                    _BaseClassRecord(
                        class_id=sym_id,
                        base_name=base_name,
                        line_start=line_start,
                        line_end=line_end,
                    )
                )

        self._visit_scope(
            statements=stmt.body,
            parent_id=sym_id,
            qual_prefix=local_qual,
            mod_info=mod_info,
            nodes=nodes,
            edges=edges,
            diagnostics=diagnostics,
            global_symbols=global_symbols,
            in_class=True,
        )

    def _extract_function(
        self,
        *,
        stmt: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_id: str,
        qual_prefix: str,
        mod_info: _ParsedModuleInfo,
        nodes: list[Node],
        edges: list[Edge],
        diagnostics: list[Diagnostic],
        global_symbols: dict[str, str],
        in_class: bool,
    ) -> None:
        local_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
        full_qual = f"{mod_info.module_name}.{local_qual}"
        sym_id = make_symbol_id("py", mod_info.rel_posix, local_qual)
        line_start = getattr(stmt, "lineno", 1)
        line_end = getattr(stmt, "end_lineno", line_start) or line_start

        is_test_func = mod_info.is_test_file and stmt.name.startswith("test_")
        kind: NodeKind = "Test" if is_test_func else ("Method" if in_class else "Function")
        signature = format_function_signature(stmt)
        decorators = [_unparse_expr(dec) for dec in stmt.decorator_list]
        doc_summary = sanitize_docstring_summary(ast.get_docstring(stmt))

        prov = Provenance(
            source_path=mod_info.rel_posix,
            line_start=line_start,
            line_end=line_end,
            extractor=EXTRACTOR_ID,
            evidence_kind="deterministic",
            confidence="high",
        )
        nodes.append(
            Node(
                id=sym_id,
                kind=kind,
                name=stmt.name,
                qualified_name=full_qual,
                attributes={
                    "signature": signature,
                    "is_async": isinstance(stmt, ast.AsyncFunctionDef),
                    "decorators": decorators,
                    "docstring_summary": doc_summary,
                },
                provenance=prov,
            )
        )
        edges.append(
            Edge(
                id=make_edge_id("DEFINES", parent_id, sym_id),
                kind="DEFINES",
                source_id=parent_id,
                target_id=sym_id,
                provenance=prov,
            )
        )

        mod_info.symbols_by_short_name.setdefault(stmt.name, sym_id)
        mod_info.symbols_by_qual_suffix[local_qual] = sym_id
        global_symbols[full_qual] = sym_id
        if is_test_func:
            mod_info.test_symbol_ids.append(sym_id)

        _collect_calls_in_body(
            stmt.body,
            caller_id=sym_id,
            rel_posix=mod_info.rel_posix,
            call_sites=mod_info.call_sites,
            diagnostics=diagnostics,
        )

        self._visit_scope(
            statements=stmt.body,
            parent_id=sym_id,
            qual_prefix=local_qual,
            mod_info=mod_info,
            nodes=nodes,
            edges=edges,
            diagnostics=diagnostics,
            global_symbols=global_symbols,
            in_class=False,
        )

    def _extract_module_constant(
        self,
        *,
        stmt: ast.Assign | ast.AnnAssign,
        parent_id: str,
        mod_info: _ParsedModuleInfo,
        nodes: list[Node],
        edges: list[Edge],
        global_symbols: dict[str, str],
    ) -> None:
        targets: list[str] = []
        annotation_str = ""
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            targets.append(stmt.target.id)
            annotation_str = _unparse_expr(stmt.annotation)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    targets.append(t.id)

        line_start = getattr(stmt, "lineno", 1)
        line_end = getattr(stmt, "end_lineno", line_start) or line_start

        for name in targets:
            if not _CONSTANT_NAME_RE.match(name):
                continue
            sym_id = make_symbol_id("py", mod_info.rel_posix, name)
            full_qual = f"{mod_info.module_name}.{name}"
            prov = Provenance(
                source_path=mod_info.rel_posix,
                line_start=line_start,
                line_end=line_end,
                extractor=EXTRACTOR_ID,
                evidence_kind="deterministic",
                confidence="high",
            )
            nodes.append(
                Node(
                    id=sym_id,
                    kind="Variable",
                    name=name,
                    qualified_name=full_qual,
                    attributes={"annotation": annotation_str},
                    provenance=prov,
                )
            )
            edges.append(
                Edge(
                    id=make_edge_id("DEFINES", parent_id, sym_id),
                    kind="DEFINES",
                    source_id=parent_id,
                    target_id=sym_id,
                    provenance=prov,
                )
            )
            mod_info.symbols_by_short_name.setdefault(name, sym_id)
            global_symbols[full_qual] = sym_id

    def _link_relationships(
        self,
        *,
        parsed_modules: dict[str, _ParsedModuleInfo],
        global_symbols: dict[str, str],
        edges: list[Edge],
    ) -> None:
        for mod_info in parsed_modules.values():
            # 1. Link IMPORTS edges
            for _bound_name, (target_qual, line_start, line_end) in sorted(
                mod_info.import_bindings.items()
            ):
                prov = Provenance(
                    source_path=mod_info.rel_posix,
                    line_start=line_start,
                    line_end=line_end,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                target_id: str | None = None
                if target_qual in global_symbols:
                    target_id = global_symbols[target_qual]
                elif target_qual in parsed_modules:
                    target_id = parsed_modules[target_qual].module_id
                else:
                    prefix_mod = ".".join(target_qual.split(".")[:-1])
                    if prefix_mod in parsed_modules:
                        target_id = parsed_modules[prefix_mod].module_id

                if target_id is not None and target_id != mod_info.module_id:
                    edges.append(
                        Edge(
                            id=make_edge_id("IMPORTS", mod_info.module_id, target_id),
                            kind="IMPORTS",
                            source_id=mod_info.module_id,
                            target_id=target_id,
                            provenance=prov,
                        )
                    )

            # 2. Link INHERITS edges
            for base_rec in mod_info.base_records:
                resolved_base = self._resolve_name_in_module(
                    base_rec.base_name,
                    mod_info=mod_info,
                    parsed_modules=parsed_modules,
                    global_symbols=global_symbols,
                )
                if resolved_base is not None and resolved_base != base_rec.class_id:
                    prov = Provenance(
                        source_path=mod_info.rel_posix,
                        line_start=base_rec.line_start,
                        line_end=base_rec.line_end,
                        extractor=EXTRACTOR_ID,
                        evidence_kind="deterministic",
                        confidence="high",
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("INHERITS", base_rec.class_id, resolved_base),
                            kind="INHERITS",
                            source_id=base_rec.class_id,
                            target_id=resolved_base,
                            provenance=prov,
                        )
                    )

            # 3. Link CALLS and TESTED_BY edges
            for call_rec in mod_info.call_sites:
                resolved_callee = self._resolve_name_in_module(
                    call_rec.callee_name,
                    mod_info=mod_info,
                    parsed_modules=parsed_modules,
                    global_symbols=global_symbols,
                )
                if resolved_callee is None or resolved_callee == call_rec.caller_id:
                    continue

                prov = Provenance(
                    source_path=mod_info.rel_posix,
                    line_start=call_rec.line_start,
                    line_end=call_rec.line_end,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                edges.append(
                    Edge(
                        id=make_edge_id("CALLS", call_rec.caller_id, resolved_callee),
                        kind="CALLS",
                        source_id=call_rec.caller_id,
                        target_id=resolved_callee,
                        provenance=prov,
                    )
                )

                if call_rec.caller_id in mod_info.test_symbol_ids:
                    edges.append(
                        Edge(
                            id=make_edge_id("TESTED_BY", resolved_callee, call_rec.caller_id),
                            kind="TESTED_BY",
                            source_id=resolved_callee,
                            target_id=call_rec.caller_id,
                            provenance=prov,
                        )
                    )

    def _resolve_name_in_module(
        self,
        raw_name: str,
        *,
        mod_info: _ParsedModuleInfo,
        parsed_modules: dict[str, _ParsedModuleInfo],
        global_symbols: dict[str, str],
    ) -> str | None:
        """Resolve a local or imported identifier (`foo` or `alias.foo` or `self.foo`)."""
        if raw_name in mod_info.symbols_by_qual_suffix:
            return mod_info.symbols_by_qual_suffix[raw_name]
        if raw_name in mod_info.symbols_by_short_name:
            return mod_info.symbols_by_short_name[raw_name]

        parts = raw_name.split(".")
        first = parts[0]

        if first in ("self", "cls") and len(parts) == 2:
            method_name = parts[1]
            if method_name in mod_info.symbols_by_short_name:
                return mod_info.symbols_by_short_name[method_name]

        if first in mod_info.import_bindings:
            imported_qual, _, _ = mod_info.import_bindings[first]
            candidate_qual = (
                f"{imported_qual}.{'.'.join(parts[1:])}" if len(parts) > 1 else imported_qual
            )
            if candidate_qual in global_symbols:
                return global_symbols[candidate_qual]
            if candidate_qual in parsed_modules:
                return parsed_modules[candidate_qual].module_id

            # Handle symbols re-exported via package __init__.py
            symbol_tail = candidate_qual.split(".")[-1]
            pkg_prefix = ".".join(candidate_qual.split(".")[:-1])
            for mod_name, target_mod in parsed_modules.items():
                if (
                    mod_name == pkg_prefix or mod_name.startswith(f"{pkg_prefix}.")
                ) and symbol_tail in target_mod.symbols_by_short_name:
                    return target_mod.symbols_by_short_name[symbol_tail]

        return None
