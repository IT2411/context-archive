"""Polyglot static source analyzer for Kotlin, Java, C/C++, Go, Rust, C#, Ruby, PHP, and Swift."""

from __future__ import annotations

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

EXTRACTOR_ID = "polyglot:1.0"

POLYGLOT_LANGUAGES: frozenset[str] = frozenset(
    {"kotlin", "java", "cpp", "go", "rust", "csharp", "ruby", "php", "swift"}
)

LANG_TAG_MAP: dict[str, str] = {
    "kotlin": "kt",
    "java": "java",
    "cpp": "cpp",
    "go": "go",
    "rust": "rs",
    "csharp": "cs",
    "ruby": "rb",
    "php": "php",
    "swift": "swift",
}

_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE)
_CPP_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE)

_JVM_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+)", re.MULTILINE)
_CPP_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE)
_GO_IMPORT_RE = re.compile(r'["`]([A-Za-z0-9_./-]+)["`]')
_RUST_USE_RE = re.compile(r"^\s*use\s+([A-Za-z0-9_:{}*,\s]+);", re.MULTILINE)

# Captures class/struct/interface/object/enum/record/trait with optional constructor params & bases
_TYPE_DECL_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_]+(?:\([^)]*\))?\s*)*"
    r"(?:public\s+|private\s+|protected\s+|internal\s+|abstract\s+|final\s+|open\s+|data\s+|sealed\s+|value\s+)*"
    r"(class|struct|interface|object|enum|record|trait)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:<[^>]+>)?"
    r"(?:\s*(?:private\s+|public\s+|internal\s+)?(?:constructor\s*)?\(([^)]*)\))?"
    r"(?:\s*(?::|extends|implements)\s*([^{\n]+))?",
    re.MULTILINE,
)

# Kotlin function supporting regular identifiers and backtick test names
_KT_FUN_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_]+(?:\([^)]*\))?\s*)*"
    r"(?:public\s+|private\s+|protected\s+|internal\s+|override\s+|open\s+|inline\s+|operator\s+|infix\s+)*"
    r"(suspend\s+)?fun\s+(?:<[^>]+>\s*)?(?:[A-Za-z0-9_<>?]+\.)?"
    r"(`[^`\n]+`|[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\(([^)]*)\)(?:\s*:\s*([^\n={]+))?",
    re.MULTILINE,
)

_C_LIKE_FUNC_RE = re.compile(
    r"^\s*(?:@[A-Za-z0-9_]+(?:\([^)]*\))?\s*)*"
    r"(?:(?:public|private|protected|internal|static|final|virtual|override|inline|explicit|constexpr|async|synchronized)\s+)*"
    r"([A-Za-z_][A-Za-z0-9_:<>,\s*&?\[\]]+?)\s+"
    r"([A-Za-z_][A-Za-z0-9_:]*)\s*\(([^;{}()]*)\)\s*(?:const\s*)?(?:noexcept\s*)?(?:throws\s+[A-Za-z0-9_,\s]+\s*)?\{",
    re.MULTILINE,
)

_CPP_TEST_MACRO_RE = re.compile(
    r"^\s*(TEST|TEST_F|TEST_P)\s*\(\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*\)",
    re.MULTILINE,
)

_OTHER_FUNC_RE = re.compile(
    r"^\s*(?:pub\s+)?(?:async\s+)?(?:func|fn|def|function)\s+"
    r"(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*\(([^)]*)\)(?:\s*(?:->|:)?\s*([^\n{=;]+))?",
    re.MULTILINE,
)

_SPRING_ROUTE_RE = re.compile(
    r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)"
    r'(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']+)["\']\s*\))?'
)

_CONTROL_KEYWORDS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "new",
        "delete",
        "sizeof",
        "typeof",
        "else",
        "do",
        "case",
        "namespace",
        "class",
        "struct",
        "when",
        "super",
        "this",
        "require",
        "check",
        "assert",
        "assertEquals",
        "assertTrue",
        "assertFalse",
        "assertNotNull",
        "listOf",
        "mapOf",
        "setOf",
        "mutableListOf",
        "mutableMapOf",
        "println",
        "print",
    }
)

_CALL_INVOCATION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_TYPE_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\b")


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _strip_test_suffix(type_name: str) -> str | None:
    """If `type_name` is `BettingEngineTest`, return `BettingEngine`."""
    for suffix in ("Tests", "Test", "Spec", "IT", "E2ETest"):
        if type_name.endswith(suffix) and len(type_name) > len(suffix):
            return type_name[: -len(suffix)]
    return None


def _compute_polyglot_module_name(rel_posix: str, source_text: str, language: str) -> str:
    """Compute a canonical module/package name from package headers or file path."""
    norm = normalize_posix_path(rel_posix)
    stem = PurePosixPath(norm).stem

    if language in ("kotlin", "java", "go"):
        pkg_match = _PACKAGE_RE.search(source_text)
        if pkg_match:
            pkg = pkg_match.group(1).strip()
            return f"{pkg}.{stem}" if language != "go" else pkg

    if language == "cpp":
        ns_match = _CPP_NAMESPACE_RE.search(source_text)
        if ns_match:
            ns = ns_match.group(1).replace("::", ".").strip(".")
            return f"{ns}.{stem}"

    parts = list(PurePosixPath(norm).parts)
    if parts and parts[0] in ("src", "app", "include", "lib") and len(parts) > 1:
        parts = parts[1:]
    if len(parts) >= 2 and parts[0] in ("main", "test") and parts[1] in ("kotlin", "java", "cpp"):
        parts = parts[2:]
    if not parts:
        return stem
    parts[-1] = stem
    return ".".join(parts)


@dataclass
class _PolyglotFileRecord:
    """Intermediate parsed state for a single polyglot source file."""

    rel_posix: str
    language: str
    lang_tag: str
    is_test_file: bool
    module_name: str
    module_id: str
    source_text: str
    defined_symbols: dict[str, str] = field(default_factory=dict)
    test_symbol_ids: list[str] = field(default_factory=list)
    raw_imports: list[tuple[str, int]] = field(default_factory=list)
    raw_bases: list[tuple[str, str, int]] = field(default_factory=list)
    raw_type_refs: list[tuple[str, str, int]] = field(default_factory=list)
    symbol_spans: list[tuple[int, str]] = field(default_factory=list)


class PolyglotAdapter:
    """Static source analyzer for Kotlin, Java, C/C++, Go, Rust, C#, Ruby, PHP, and Swift."""

    @property
    def adapter_id(self) -> str:
        return EXTRACTOR_ID

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        return scanned_file.language in POLYGLOT_LANGUAGES and scanned_file.category in (
            "source_code",
            "test",
        )

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
    ) -> AdapterExtractionResult:
        """Extract File, Module, Class, Schema, Function, Method, Endpoint, and Test nodes."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        diagnostics: list[Diagnostic] = []

        target_files = sorted(
            (f for f in files if self.can_handle(f)),
            key=lambda item: item.path,
        )
        if not target_files:
            return AdapterExtractionResult()

        file_records: list[_PolyglotFileRecord] = []
        global_symbols_by_name: dict[str, str] = {}
        global_symbols_by_qual: dict[str, str] = {}
        module_by_stem: dict[str, str] = {}
        module_by_name: dict[str, str] = {}

        for scanned in target_files:
            rel_posix = normalize_posix_path(scanned.path)
            lang = scanned.language or "unknown"
            lang_tag = LANG_TAG_MAP.get(lang, lang)
            try:
                source_text = (repo_root / rel_posix).read_text(encoding="utf-8")
            except OSError:  # pragma: no cover
                continue

            lines = source_text.splitlines()
            line_count = max(1, len(lines))
            file_id = make_file_id(rel_posix)
            mod_name = _compute_polyglot_module_name(rel_posix, source_text, lang)
            mod_id = make_module_id(lang_tag, rel_posix, mod_name)
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
                    attributes={"language": lang, "size_bytes": scanned.size_bytes},
                    provenance=file_prov,
                )
            )
            nodes.append(
                Node(
                    id=mod_id,
                    kind="Module",
                    name=PurePosixPath(rel_posix).stem,
                    qualified_name=mod_name,
                    attributes={
                        "language": lang,
                        "docstring_summary": f"{lang.capitalize()} module {mod_name}",
                        "is_test_module": is_test_file,
                    },
                    provenance=file_prov,
                )
            )
            edges.append(
                Edge(
                    id=make_edge_id("CONTAINS", file_id, mod_id),
                    kind="CONTAINS",
                    source_id=file_id,
                    target_id=mod_id,
                    provenance=file_prov,
                )
            )

            module_by_stem[PurePosixPath(rel_posix).name] = mod_id
            module_by_stem[PurePosixPath(rel_posix).stem] = mod_id
            module_by_name[mod_name] = mod_id

            rec = _PolyglotFileRecord(
                rel_posix=rel_posix,
                language=lang,
                lang_tag=lang_tag,
                is_test_file=is_test_file,
                module_name=mod_name,
                module_id=mod_id,
                source_text=source_text,
            )
            file_records.append(rec)

            self._extract_imports(rec)
            self._extract_types(rec, nodes, edges, global_symbols_by_name, global_symbols_by_qual)
            self._extract_functions(
                rec, nodes, edges, global_symbols_by_name, global_symbols_by_qual
            )

        self._link_cross_file_edges(
            file_records=file_records,
            module_by_stem=module_by_stem,
            module_by_name=module_by_name,
            global_symbols_by_name=global_symbols_by_name,
            global_symbols_by_qual=global_symbols_by_qual,
            edges=edges,
        )

        return AdapterExtractionResult(
            nodes=tuple(nodes),
            edges=tuple(edges),
            diagnostics=tuple(diagnostics),
        )

    def _extract_imports(self, rec: _PolyglotFileRecord) -> None:
        text = rec.source_text
        if rec.language in ("kotlin", "java"):
            for m in _JVM_IMPORT_RE.finditer(text):
                rec.raw_imports.append((m.group(1).strip(), _line_at(text, m.start())))
        elif rec.language == "cpp":
            for m in _CPP_INCLUDE_RE.finditer(text):
                rec.raw_imports.append((m.group(1).strip(), _line_at(text, m.start())))
        elif rec.language == "go":
            for m in _GO_IMPORT_RE.finditer(text):
                rec.raw_imports.append((m.group(1).strip(), _line_at(text, m.start())))
        elif rec.language == "rust":
            for m in _RUST_USE_RE.finditer(text):
                rec.raw_imports.append((m.group(1).strip(), _line_at(text, m.start())))

    def _extract_types(
        self,
        rec: _PolyglotFileRecord,
        nodes: list[Node],
        edges: list[Edge],
        global_by_name: dict[str, str],
        global_by_qual: dict[str, str],
    ) -> None:
        for match in _TYPE_DECL_RE.finditer(rec.source_text):
            kw = match.group(1)
            type_name = match.group(2)
            if type_name in _CONTROL_KEYWORDS:
                continue
            ctor_params = (match.group(3) or "").strip()
            bases_raw = (match.group(4) or "").strip()
            line_no = _line_at(rec.source_text, match.start())

            is_test_class = rec.is_test_file and type_name.endswith(
                ("Test", "Tests", "Spec", "E2ETest")
            )
            if is_test_class:
                kind: NodeKind = "Test"
            elif kw in ("interface", "trait"):
                kind = "Schema"
            else:
                kind = "Class"

            prefix = f"schema:{rec.lang_tag}" if kind == "Schema" else rec.lang_tag
            sym_id = make_symbol_id(prefix, rec.rel_posix, type_name)
            full_qual = f"{rec.module_name}.{type_name}"

            base_list: list[str] = []
            if bases_raw:
                for token in re.split(r"[,:]|\bextends\b|\bimplements\b", bases_raw):
                    cleaned = token.strip().split("<")[0].split("(")[0].strip()
                    if cleaned and cleaned not in ("public", "private", "protected", "virtual"):
                        base_list.append(cleaned)
                        rec.raw_bases.append(
                            (sym_id, cleaned.split(".")[-1].split("::")[-1], line_no)
                        )

            # Extract constructor parameter type references (`val engine: BettingEngine`)
            if ctor_params:
                for type_tok in _TYPE_TOKEN_RE.findall(ctor_params):
                    if type_tok != type_name:
                        rec.raw_type_refs.append((sym_id, type_tok, line_no))

            prov = Provenance(
                source_path=rec.rel_posix,
                line_start=line_no,
                line_end=line_no,
                extractor=EXTRACTOR_ID,
                evidence_kind="deterministic",
                confidence="high",
            )
            ctor_sig = f"({ ' '.join(ctor_params.split()) })" if ctor_params else ""
            nodes.append(
                Node(
                    id=sym_id,
                    kind=kind,
                    name=type_name,
                    qualified_name=full_qual,
                    attributes={
                        "language": rec.language,
                        "declaration_kind": kw,
                        "bases": base_list,
                        "signature": f"{kw} {type_name}{ctor_sig}",
                        "docstring_summary": "",
                    },
                    provenance=prov,
                )
            )
            edges.append(
                Edge(
                    id=make_edge_id("DEFINES", rec.module_id, sym_id),
                    kind="DEFINES",
                    source_id=rec.module_id,
                    target_id=sym_id,
                    provenance=prov,
                )
            )
            rec.defined_symbols[type_name] = sym_id
            rec.symbol_spans.append((line_no, sym_id))
            if is_test_class:
                rec.test_symbol_ids.append(sym_id)
            global_by_name.setdefault(type_name, sym_id)
            global_by_qual[full_qual] = sym_id

    def _extract_functions(
        self,
        rec: _PolyglotFileRecord,
        nodes: list[Node],
        edges: list[Edge],
        global_by_name: dict[str, str],
        global_by_qual: dict[str, str],
    ) -> None:
        text = rec.source_text
        seen_names_at_line: set[tuple[str, int]] = set()

        if rec.language == "kotlin":
            for m in _KT_FUN_RE.finditer(text):
                is_suspend = bool(m.group(1))
                raw_fn_name = m.group(2).strip("`")
                fn_name = re.sub(r"\s+", "_", raw_fn_name)
                params = " ".join(m.group(3).split())
                ret_type = (m.group(4) or "Unit").strip()
                line_no = _line_at(text, m.start())
                snippet_before = text[max(0, m.start() - 160) : m.end()]
                is_test = rec.is_test_file and (
                    fn_name.startswith("test") or "@Test" in snippet_before
                )
                sym_id = self._register_callable(
                    rec=rec,
                    fn_name=fn_name,
                    sig=f"({params}) -> {ret_type}",
                    is_async=is_suspend,
                    is_test=is_test,
                    line_no=line_no,
                    snippet_before=snippet_before,
                    nodes=nodes,
                    edges=edges,
                    global_by_name=global_by_name,
                    global_by_qual=global_by_qual,
                    seen=seen_names_at_line,
                )
                if sym_id is not None:
                    for type_tok in _TYPE_TOKEN_RE.findall(f"{params} {ret_type}"):
                        rec.raw_type_refs.append((sym_id, type_tok, line_no))
            return

        if rec.language == "cpp":
            for tm in _CPP_TEST_MACRO_RE.finditer(text):
                suite = tm.group(2)
                case_name = tm.group(3)
                fn_name = f"{suite}_{case_name}"
                line_no = _line_at(text, tm.start())
                self._register_callable(
                    rec=rec,
                    fn_name=fn_name,
                    sig=f"({suite}, {case_name})",
                    is_async=False,
                    is_test=True,
                    line_no=line_no,
                    snippet_before="",
                    nodes=nodes,
                    edges=edges,
                    global_by_name=global_by_name,
                    global_by_qual=global_by_qual,
                    seen=seen_names_at_line,
                )

        if rec.language in ("java", "cpp", "csharp"):
            for cm in _C_LIKE_FUNC_RE.finditer(text):
                ret_type = " ".join(cm.group(1).split())
                raw_fn_name = cm.group(2).strip()
                fn_name = raw_fn_name.split("::")[-1]
                if fn_name in _CONTROL_KEYWORDS or ret_type in _CONTROL_KEYWORDS:
                    continue
                params = " ".join(cm.group(3).split())
                line_no = _line_at(text, cm.start())
                snippet_before = text[max(0, cm.start() - 160) : cm.end()]
                is_test = rec.is_test_file and (
                    fn_name.startswith("test") or "@Test" in snippet_before
                )
                sym_id = self._register_callable(
                    rec=rec,
                    fn_name=fn_name,
                    sig=f"({params}) -> {ret_type}",
                    is_async="async" in snippet_before,
                    is_test=is_test,
                    line_no=line_no,
                    snippet_before=snippet_before,
                    nodes=nodes,
                    edges=edges,
                    global_by_name=global_by_name,
                    global_by_qual=global_by_qual,
                    seen=seen_names_at_line,
                )
                if sym_id is not None:
                    for type_tok in _TYPE_TOKEN_RE.findall(f"{params} {ret_type}"):
                        rec.raw_type_refs.append((sym_id, type_tok, line_no))
            return

        for om in _OTHER_FUNC_RE.finditer(text):
            fn_name = om.group(1)
            if fn_name in _CONTROL_KEYWORDS:
                continue
            params = " ".join(om.group(2).split())
            ret_type = (om.group(3) or "").strip()
            sig = f"({params}) -> {ret_type}" if ret_type else f"({params})"
            line_no = _line_at(text, om.start())
            snippet_before = text[max(0, om.start() - 100) : om.end()]
            is_test = rec.is_test_file and (
                fn_name.startswith(("test", "Test")) or "#[test]" in snippet_before
            )
            self._register_callable(
                rec=rec,
                fn_name=fn_name,
                sig=sig,
                is_async="async" in snippet_before,
                is_test=is_test,
                line_no=line_no,
                snippet_before=snippet_before,
                nodes=nodes,
                edges=edges,
                global_by_name=global_by_name,
                global_by_qual=global_by_qual,
                seen=seen_names_at_line,
            )

    def _register_callable(
        self,
        *,
        rec: _PolyglotFileRecord,
        fn_name: str,
        sig: str,
        is_async: bool,
        is_test: bool,
        line_no: int,
        snippet_before: str,
        nodes: list[Node],
        edges: list[Edge],
        global_by_name: dict[str, str],
        global_by_qual: dict[str, str],
        seen: set[tuple[str, int]],
    ) -> str | None:
        if (fn_name, line_no) in seen:
            return None
        seen.add((fn_name, line_no))

        kind: NodeKind = "Test" if is_test else "Function"
        sym_id = make_symbol_id(rec.lang_tag, rec.rel_posix, fn_name)
        full_qual = f"{rec.module_name}.{fn_name}"
        prov = Provenance(
            source_path=rec.rel_posix,
            line_start=line_no,
            line_end=line_no,
            extractor=EXTRACTOR_ID,
            evidence_kind="deterministic",
            confidence="high",
        )
        nodes.append(
            Node(
                id=sym_id,
                kind=kind,
                name=fn_name,
                qualified_name=full_qual,
                attributes={
                    "language": rec.language,
                    "signature": sig,
                    "is_async": is_async,
                    "decorators": [],
                    "docstring_summary": "",
                },
                provenance=prov,
            )
        )
        edges.append(
            Edge(
                id=make_edge_id("DEFINES", rec.module_id, sym_id),
                kind="DEFINES",
                source_id=rec.module_id,
                target_id=sym_id,
                provenance=prov,
            )
        )
        rec.defined_symbols[fn_name] = sym_id
        rec.symbol_spans.append((line_no, sym_id))
        if is_test:
            rec.test_symbol_ids.append(sym_id)
        global_by_name.setdefault(fn_name, sym_id)
        global_by_qual[full_qual] = sym_id

        route_match = _SPRING_ROUTE_RE.search(snippet_before)
        if route_match:
            ann_name = route_match.group(1)
            route_path = route_match.group(2) or "/"
            http_method = (
                ann_name.replace("Mapping", "").upper() if ann_name != "RequestMapping" else "GET"
            )
            ep_name = f"{http_method} {route_path}"
            ep_id = make_symbol_id(
                f"endpoint:{rec.lang_tag}", rec.rel_posix, f"{http_method}:{route_path}"
            )
            nodes.append(
                Node(
                    id=ep_id,
                    kind="Endpoint",
                    name=ep_name,
                    qualified_name=ep_name,
                    attributes={
                        "http_method": http_method,
                        "route_path": route_path,
                        "handler": full_qual,
                        "signature": f"[{http_method} {route_path}]",
                    },
                    provenance=prov,
                )
            )
            edges.append(
                Edge(
                    id=make_edge_id("EXPOSES", sym_id, ep_id),
                    kind="EXPOSES",
                    source_id=sym_id,
                    target_id=ep_id,
                    provenance=prov,
                )
            )
        return sym_id

    def _link_cross_file_edges(
        self,
        *,
        file_records: list[_PolyglotFileRecord],
        module_by_stem: dict[str, str],
        module_by_name: dict[str, str],
        global_symbols_by_name: dict[str, str],
        global_symbols_by_qual: dict[str, str],
        edges: list[Edge],
    ) -> None:
        for rec in file_records:
            # 1. IMPORTS edges
            for imp_str, line_no in rec.raw_imports:
                target_id: str | None = None
                cleaned_imp = imp_str.rstrip(".*")
                tail_name = PurePosixPath(cleaned_imp.replace(".", "/")).name
                if cleaned_imp in global_symbols_by_qual:
                    target_id = global_symbols_by_qual[cleaned_imp]
                elif cleaned_imp in module_by_name:
                    target_id = module_by_name[cleaned_imp]
                elif PurePosixPath(imp_str).name in module_by_stem:
                    target_id = module_by_stem[PurePosixPath(imp_str).name]
                elif tail_name in global_symbols_by_name:
                    target_id = global_symbols_by_name[tail_name]

                if target_id is not None and target_id != rec.module_id:
                    prov = Provenance(
                        source_path=rec.rel_posix,
                        line_start=line_no,
                        line_end=line_no,
                        extractor=EXTRACTOR_ID,
                        evidence_kind="deterministic",
                        confidence="high",
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("IMPORTS", rec.module_id, target_id),
                            kind="IMPORTS",
                            source_id=rec.module_id,
                            target_id=target_id,
                            provenance=prov,
                        )
                    )

            # 2. INHERITS edges
            for class_id, base_short, line_no in rec.raw_bases:
                base_id = global_symbols_by_name.get(base_short)
                if base_id is not None and base_id != class_id:
                    prov = Provenance(
                        source_path=rec.rel_posix,
                        line_start=line_no,
                        line_end=line_no,
                        extractor=EXTRACTOR_ID,
                        evidence_kind="deterministic",
                        confidence="high",
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("INHERITS", class_id, base_id),
                            kind="INHERITS",
                            source_id=class_id,
                            target_id=base_id,
                            provenance=prov,
                        )
                    )

            # 3. DEPENDS_ON edges from constructor/method parameter & return types
            for src_sym_id, ref_type_name, line_no in rec.raw_type_refs:
                target_type_id = global_symbols_by_name.get(ref_type_name)
                if target_type_id is not None and target_type_id != src_sym_id:
                    prov = Provenance(
                        source_path=rec.rel_posix,
                        line_start=line_no,
                        line_end=line_no,
                        extractor=EXTRACTOR_ID,
                        evidence_kind="deterministic",
                        confidence="high",
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("DEPENDS_ON", src_sym_id, target_type_id),
                            kind="DEPENDS_ON",
                            source_id=src_sym_id,
                            target_id=target_type_id,
                            provenance=prov,
                        )
                    )

            # 4. Naming-convention & body-reference TESTED_BY linking for test classes/files
            if rec.is_test_file:
                file_stem = PurePosixPath(rec.rel_posix).stem
                target_class_name = _strip_test_suffix(file_stem)
                primary_test_id = rec.test_symbol_ids[0] if rec.test_symbol_ids else rec.module_id
                if target_class_name and target_class_name in global_symbols_by_name:
                    tested_id = global_symbols_by_name[target_class_name]
                    if tested_id != primary_test_id:
                        prov = Provenance(
                            source_path=rec.rel_posix,
                            line_start=1,
                            line_end=1,
                            extractor=EXTRACTOR_ID,
                            evidence_kind="deterministic",
                            confidence="high",
                        )
                        edges.append(
                            Edge(
                                id=make_edge_id("TESTED_BY", tested_id, primary_test_id),
                                kind="TESTED_BY",
                                source_id=tested_id,
                                target_id=primary_test_id,
                                provenance=prov,
                            )
                        )

                # Also link any repo class/type referenced inside a test file to `primary_test_id`
                for type_m in _TYPE_TOKEN_RE.finditer(rec.source_text):
                    ref_name = type_m.group(1)
                    ref_id = global_symbols_by_name.get(ref_name)
                    if (
                        ref_id is not None
                        and ref_id not in rec.test_symbol_ids
                        and ref_id not in rec.defined_symbols.values()
                    ):
                        line_no = _line_at(rec.source_text, type_m.start())
                        prov = Provenance(
                            source_path=rec.rel_posix,
                            line_start=line_no,
                            line_end=line_no,
                            extractor=EXTRACTOR_ID,
                            evidence_kind="deterministic",
                            confidence="high",
                        )
                        edges.append(
                            Edge(
                                id=make_edge_id("TESTED_BY", ref_id, primary_test_id),
                                kind="TESTED_BY",
                                source_id=ref_id,
                                target_id=primary_test_id,
                                provenance=prov,
                            )
                        )

            # 5. CALLS and TESTED_BY edges from function/constructor invocations
            rec.symbol_spans.sort(key=lambda item: item[0])
            for call_m in _CALL_INVOCATION_RE.finditer(rec.source_text):
                callee_name = call_m.group(1)
                if callee_name in _CONTROL_KEYWORDS:
                    continue
                target_sym_id = global_symbols_by_name.get(callee_name)
                if target_sym_id is None:
                    continue

                call_line = _line_at(rec.source_text, call_m.start())
                caller_id = rec.module_id
                for span_line, sym_id in rec.symbol_spans:
                    if span_line < call_line:
                        caller_id = sym_id
                    elif span_line == call_line:
                        caller_id = sym_id
                        break
                    else:
                        break

                if caller_id == target_sym_id:
                    continue

                prov = Provenance(
                    source_path=rec.rel_posix,
                    line_start=call_line,
                    line_end=call_line,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                edges.append(
                    Edge(
                        id=make_edge_id("CALLS", caller_id, target_sym_id),
                        kind="CALLS",
                        source_id=caller_id,
                        target_id=target_sym_id,
                        provenance=prov,
                    )
                )
                if caller_id in rec.test_symbol_ids or rec.is_test_file:
                    test_owner_id = (
                        caller_id
                        if caller_id in rec.test_symbol_ids
                        else (rec.test_symbol_ids[0] if rec.test_symbol_ids else caller_id)
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("TESTED_BY", target_sym_id, test_owner_id),
                            kind="TESTED_BY",
                            source_id=target_sym_id,
                            target_id=test_owner_id,
                            provenance=prov,
                        )
                    )
