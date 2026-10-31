"""TypeScript/JavaScript static analyzer and cross-stack API contract linker (SRS FR-06)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from context_archive.adapters.base import AdapterExtractionResult
from context_archive.model.graph import Diagnostic, Edge, Node
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

EXTRACTOR_ID = "typescript:1.0"

_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:type\s+)?(?:[^'"]+\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_EXPORT_FUNC_RE = re.compile(
    r"""^\s*export\s+(?:default\s+)?(async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)(?:\s*:\s*([^\n{]+))?""",
    re.MULTILINE,
)
_EXPORT_CONST_FUNC_RE = re.compile(
    r"""^\s*export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(async\s+)?\(([^)]*)\)(?:\s*:\s*([^\n=]+))?\s*=>""",
    re.MULTILINE,
)
_INTERFACE_RE = re.compile(
    r"""^\s*(?:export\s+)?(?:interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)""",
    re.MULTILINE,
)
_FETCH_RE = re.compile(
    r"""fetch\(\s*(['"`])([^'"`]+)\1(?:\s*,\s*\{[^}]*?method\s*:\s*['"]([A-Za-z]+)['"][^}]*\})?""",
    re.DOTALL,
)
_AXIOS_RE = re.compile(
    r"""axios\.(get|post|put|delete|patch)(?:<[^>]+>)?\(\s*(['"`])([^'"`]+)\2""",
    re.IGNORECASE,
)


def _compute_ts_module_name(rel_posix: str) -> str:
    norm = normalize_posix_path(rel_posix)
    parts = list(PurePosixPath(norm).parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if not parts:
        return "root"
    parts[-1] = PurePosixPath(parts[-1]).stem
    if parts[-1] == "index" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def _line_number_at_offset(source_text: str, offset: int) -> int:
    return source_text.count("\n", 0, offset) + 1


def _normalize_url_path(raw_url: str) -> tuple[str, bool]:
    """Normalize a frontend URL string (`/api/orders/${id}` -> `('/orders/{param}', True)`)."""
    cleaned = raw_url.strip()
    cleaned = re.sub(r"^https?://[^/]+", "", cleaned)
    cleaned = re.sub(r"^/api(?=/|$)", "", cleaned)
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    has_interpolation = "${" in cleaned
    normalized = re.sub(r"\$\{[^}]+\}", "{param}", cleaned)
    return normalized, has_interpolation


def _route_matches_template(endpoint_route: str, client_route: str) -> bool:
    """Return True if a client URL path matches a backend FastAPI route path."""
    if endpoint_route == client_route:
        return True
    ep_parts = [p for p in endpoint_route.strip("/").split("/") if p]
    cl_parts = [p for p in client_route.strip("/").split("/") if p]
    if len(ep_parts) != len(cl_parts):
        return False
    for ep_seg, cl_seg in zip(ep_parts, cl_parts, strict=False):
        if ep_seg == cl_seg:
            continue
        if (ep_seg.startswith("{") and ep_seg.endswith("}")) or cl_seg == "{param}":
            continue
        return False
    return True


class TypeScriptAdapter:
    """Static TypeScript/JavaScript analyzer and cross-stack API consumer linker."""

    @property
    def adapter_id(self) -> str:
        return EXTRACTOR_ID

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        return scanned_file.language in ("typescript", "javascript") and scanned_file.category in (
            "source_code",
            "test",
        )

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
        *,
        existing_nodes: tuple[Node, ...] | list[Node] = (),
    ) -> AdapterExtractionResult:
        """Extract TS/JS files, modules, functions, interfaces, imports, and API CONSUMES edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        diagnostics: list[Diagnostic] = []

        ts_files = sorted(
            (f for f in files if self.can_handle(f)),
            key=lambda item: item.path,
        )
        if not ts_files:
            return AdapterExtractionResult()

        endpoint_nodes = [n for n in existing_nodes if n.kind == "Endpoint"]
        module_id_by_rel_stem: dict[str, str] = {}
        pending_imports: list[tuple[str, str, str, int]] = []

        for scanned in ts_files:
            rel_posix = normalize_posix_path(scanned.path)
            try:
                source_text = (repo_root / rel_posix).read_text(encoding="utf-8")
            except OSError:  # pragma: no cover
                continue

            lines = source_text.splitlines()
            line_count = max(1, len(lines))
            lang_tag = "ts" if scanned.language == "typescript" else "js"
            file_id = make_file_id(rel_posix)
            mod_name = _compute_ts_module_name(rel_posix)
            mod_id = make_module_id(lang_tag, rel_posix, mod_name)

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
                    attributes={"language": scanned.language, "size_bytes": scanned.size_bytes},
                    provenance=file_prov,
                )
            )
            nodes.append(
                Node(
                    id=mod_id,
                    kind="Module",
                    name=mod_name.split(".")[-1],
                    qualified_name=mod_name,
                    attributes={"docstring_summary": f"TypeScript/JavaScript module {mod_name}"},
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

            stem_no_ext = str(PurePosixPath(rel_posix).with_suffix(""))
            module_id_by_rel_stem[stem_no_ext] = mod_id

            # 1. Extract ES module imports
            for imp_match in _IMPORT_RE.finditer(source_text):
                specifier = imp_match.group(1).strip()
                line_no = _line_number_at_offset(source_text, imp_match.start())
                pending_imports.append((mod_id, rel_posix, specifier, line_no))

            # 2. Extract TypeScript interfaces / types as Schema nodes
            for iface_match in _INTERFACE_RE.finditer(source_text):
                iface_name = iface_match.group(1)
                line_no = _line_number_at_offset(source_text, iface_match.start())
                schema_id = make_symbol_id(f"schema:{lang_tag}", rel_posix, iface_name)
                prov = Provenance(
                    source_path=rel_posix,
                    line_start=line_no,
                    line_end=line_no,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                nodes.append(
                    Node(
                        id=schema_id,
                        kind="Schema",
                        name=iface_name,
                        qualified_name=f"{mod_name}.{iface_name}",
                        attributes={"signature": f"interface {iface_name}"},
                        provenance=prov,
                    )
                )
                edges.append(
                    Edge(
                        id=make_edge_id("DEFINES", mod_id, schema_id),
                        kind="DEFINES",
                        source_id=mod_id,
                        target_id=schema_id,
                        provenance=prov,
                    )
                )

            # 3. Extract exported functions
            file_func_spans: list[tuple[int, str]] = []
            for fn_match in _EXPORT_FUNC_RE.finditer(source_text):
                is_async = bool(fn_match.group(1))
                fn_name = fn_match.group(2)
                params = " ".join(fn_match.group(3).split())
                ret_type = (fn_match.group(4) or "").strip()
                line_no = _line_number_at_offset(source_text, fn_match.start())
                fn_id = make_symbol_id(lang_tag, rel_posix, fn_name)
                sig = f"({params}) -> {ret_type}" if ret_type else f"({params})"
                prov = Provenance(
                    source_path=rel_posix,
                    line_start=line_no,
                    line_end=line_no,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                nodes.append(
                    Node(
                        id=fn_id,
                        kind="Function",
                        name=fn_name,
                        qualified_name=f"{mod_name}.{fn_name}",
                        attributes={
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
                        id=make_edge_id("DEFINES", mod_id, fn_id),
                        kind="DEFINES",
                        source_id=mod_id,
                        target_id=fn_id,
                        provenance=prov,
                    )
                )
                file_func_spans.append((line_no, fn_id))

            for cfn_match in _EXPORT_CONST_FUNC_RE.finditer(source_text):
                fn_name = cfn_match.group(1)
                is_async = bool(cfn_match.group(2))
                params = " ".join(cfn_match.group(3).split())
                ret_type = (cfn_match.group(4) or "").strip()
                line_no = _line_number_at_offset(source_text, cfn_match.start())
                fn_id = make_symbol_id(lang_tag, rel_posix, fn_name)
                sig = f"({params}) -> {ret_type}" if ret_type else f"({params})"
                prov = Provenance(
                    source_path=rel_posix,
                    line_start=line_no,
                    line_end=line_no,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                nodes.append(
                    Node(
                        id=fn_id,
                        kind="Function",
                        name=fn_name,
                        qualified_name=f"{mod_name}.{fn_name}",
                        attributes={
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
                        id=make_edge_id("DEFINES", mod_id, fn_id),
                        kind="DEFINES",
                        source_id=mod_id,
                        target_id=fn_id,
                        provenance=prov,
                    )
                )
                file_func_spans.append((line_no, fn_id))

            file_func_spans.sort(key=lambda item: item[0])

            # 4. Extract fetch(...) and axios.<method>(...) API call sites and link CONSUMES
            api_calls: list[tuple[str, str, int]] = []
            for f_match in _FETCH_RE.finditer(source_text):
                raw_url = f_match.group(2)
                http_m = (f_match.group(3) or "GET").upper()
                line_no = _line_number_at_offset(source_text, f_match.start())
                api_calls.append((http_m, raw_url, line_no))

            for ax_match in _AXIOS_RE.finditer(source_text):
                http_m = ax_match.group(1).upper()
                raw_url = ax_match.group(3)
                line_no = _line_number_at_offset(source_text, ax_match.start())
                api_calls.append((http_m, raw_url, line_no))

            for http_m, raw_url, line_no in api_calls:
                norm_path, is_interpolated = _normalize_url_path(raw_url)
                caller_id = mod_id
                for fn_line, fn_id in file_func_spans:
                    if fn_line <= line_no:
                        caller_id = fn_id
                    else:
                        break

                for ep in endpoint_nodes:
                    ep_method = str(ep.attributes.get("http_method", "GET")).upper()
                    ep_route = str(ep.attributes.get("route_path", "/"))
                    if ep_method == http_m and _route_matches_template(ep_route, norm_path):
                        prov = Provenance(
                            source_path=rel_posix,
                            line_start=line_no,
                            line_end=line_no,
                            extractor=EXTRACTOR_ID,
                            evidence_kind="heuristic" if is_interpolated else "deterministic",
                            confidence="medium" if is_interpolated else "high",
                        )
                        edges.append(
                            Edge(
                                id=make_edge_id("CONSUMES", caller_id, ep.id),
                                kind="CONSUMES",
                                source_id=caller_id,
                                target_id=ep.id,
                                provenance=prov,
                            )
                        )

        # Resolve intra-repository relative TS/JS imports
        for src_mod_id, rel_posix, specifier, line_no in pending_imports:
            if not specifier.startswith("."):
                continue
            parent_dir = PurePosixPath(rel_posix).parent
            resolved_stem = normalize_posix_path((parent_dir / specifier).as_posix())
            target_mod_id = module_id_by_rel_stem.get(resolved_stem) or module_id_by_rel_stem.get(
                f"{resolved_stem}/index"
            )
            if target_mod_id is not None and target_mod_id != src_mod_id:
                prov = Provenance(
                    source_path=rel_posix,
                    line_start=line_no,
                    line_end=line_no,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                edges.append(
                    Edge(
                        id=make_edge_id("IMPORTS", src_mod_id, target_mod_id),
                        kind="IMPORTS",
                        source_id=src_mod_id,
                        target_id=target_mod_id,
                        provenance=prov,
                    )
                )

        return AdapterExtractionResult(
            nodes=tuple(nodes),
            edges=tuple(edges),
            diagnostics=tuple(diagnostics),
        )
