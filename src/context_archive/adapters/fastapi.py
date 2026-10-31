"""FastAPI route, Depends, and Pydantic BaseModel contract extractor (SRS FR-06)."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from context_archive.adapters.base import AdapterExtractionResult
from context_archive.adapters.python_ast import (
    compute_python_module_name,
    sanitize_docstring_summary,
)
from context_archive.model.graph import Diagnostic, Edge, Node
from context_archive.model.ids import make_edge_id, make_symbol_id, normalize_posix_path
from context_archive.model.provenance import Provenance

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.scanner.report import ScannedFile

EXTRACTOR_ID = "fastapi_pydantic:1.0"
HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch"})
PYDANTIC_BASE_NAMES = frozenset({"BaseModel", "SQLModel"})


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return ""


def _extract_route_decorator(
    dec: ast.expr,
) -> tuple[str, str, str | None, int | None] | None:
    """Inspect a decorator for `@app.<method>("/path", response_model=..., status_code=...)`.

    Returns `(HTTP_METHOD, route_path, response_model_name, status_code)` or `None`.
    """
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None

    method_lower = dec.func.attr.lower()
    if method_lower not in HTTP_METHODS:
        return None

    route_path = "/"
    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
        route_path = dec.args[0].value

    response_model: str | None = None
    status_code: int | None = None
    for kw in dec.keywords:
        if kw.arg == "response_model":
            response_model = _unparse(kw.value).split(".")[-1] or None
        elif (
            kw.arg == "status_code"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, int)
        ):
            status_code = kw.value.value

    return method_lower.upper(), route_path, response_model, status_code


def _extract_depends_target(default_expr: ast.expr) -> str | None:
    """Return dependency callable name if `default_expr` is `Depends(callable_name)`."""
    if not isinstance(default_expr, ast.Call):
        return None
    func_name = _unparse(default_expr.func).split(".")[-1]
    if func_name != "Depends" or not default_expr.args:
        return None
    target = _unparse(default_expr.args[0]).split(".")[-1]
    return target or None


class FastApiContractExtractor:
    """Static AST extractor for FastAPI endpoints and Pydantic schemas."""

    @property
    def adapter_id(self) -> str:
        return EXTRACTOR_ID

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        return scanned_file.language == "python" and scanned_file.category == "source_code"

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
        *,
        existing_nodes: tuple[Node, ...] | list[Node] = (),
    ) -> AdapterExtractionResult:
        """Extract Schema and Endpoint nodes and link EXPOSES, VALIDATES_WITH, and DEPENDS_ON."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        diagnostics: list[Diagnostic] = []

        py_files = sorted(
            (f for f in files if self.can_handle(f)),
            key=lambda item: item.path,
        )

        # Lookup map of short symbol name -> Node ID for linking handlers, schemas, and dependencies
        symbol_by_short_name: dict[str, str] = {}
        for existing in existing_nodes:
            if existing.kind in ("Function", "Method", "Class"):
                symbol_by_short_name.setdefault(existing.name, existing.id)

        schema_id_by_name: dict[str, str] = {}
        pending_endpoints: list[tuple[str, str, str, list[str], list[str], Provenance]] = []

        for scanned in py_files:
            rel_posix = normalize_posix_path(scanned.path)
            try:
                source_text = (repo_root / rel_posix).read_text(encoding="utf-8")
                tree = ast.parse(source_text, filename=rel_posix)
            except (OSError, SyntaxError, ValueError):
                continue

            mod_name = compute_python_module_name(rel_posix)

            for stmt in tree.body:
                if isinstance(stmt, ast.ClassDef):
                    base_names = {_unparse(b).split(".")[-1] for b in stmt.bases}
                    if base_names & PYDANTIC_BASE_NAMES:
                        fields_info: list[dict[str, str]] = []
                        for body_item in stmt.body:
                            if isinstance(body_item, ast.AnnAssign) and isinstance(
                                body_item.target, ast.Name
                            ):
                                fname = body_item.target.id
                                if fname.startswith("_"):
                                    continue
                                ftype = _unparse(body_item.annotation)
                                fdefault = (
                                    _unparse(body_item.value) if body_item.value is not None else ""
                                )
                                fields_info.append(
                                    {"name": fname, "type": ftype, "default": fdefault}
                                )

                        line_start = getattr(stmt, "lineno", 1)
                        line_end = getattr(stmt, "end_lineno", line_start) or line_start
                        schema_id = make_symbol_id("schema:py", rel_posix, stmt.name)
                        prov = Provenance(
                            source_path=rel_posix,
                            line_start=line_start,
                            line_end=line_end,
                            extractor=EXTRACTOR_ID,
                            evidence_kind="deterministic",
                            confidence="high",
                        )
                        field_summary = ", ".join(f"{f['name']}: {f['type']}" for f in fields_info)
                        nodes.append(
                            Node(
                                id=schema_id,
                                kind="Schema",
                                name=stmt.name,
                                qualified_name=f"{mod_name}.{stmt.name}",
                                attributes={
                                    "fields": fields_info,
                                    "signature": f"({field_summary})",
                                    "docstring_summary": sanitize_docstring_summary(
                                        ast.get_docstring(stmt)
                                    ),
                                },
                                provenance=prov,
                            )
                        )
                        schema_id_by_name[stmt.name] = schema_id

                elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                    for dec in stmt.decorator_list:
                        route_info = _extract_route_decorator(dec)
                        if route_info is None:
                            continue
                        http_method, route_path, resp_model, status_code = route_info
                        line_start = getattr(stmt, "lineno", 1)
                        line_end = getattr(stmt, "end_lineno", line_start) or line_start
                        endpoint_name = f"{http_method} {route_path}"
                        endpoint_id = make_symbol_id(
                            "endpoint:py", rel_posix, f"{http_method}:{route_path}"
                        )
                        prov = Provenance(
                            source_path=rel_posix,
                            line_start=line_start,
                            line_end=line_end,
                            extractor=EXTRACTOR_ID,
                            evidence_kind="deterministic",
                            confidence="high",
                        )

                        # Inspect parameters for Pydantic request schemas and Depends(...)
                        schema_refs: list[str] = []
                        if resp_model:
                            schema_refs.append(resp_model)

                        all_args = list(stmt.args.posonlyargs) + list(stmt.args.args)
                        for arg in all_args:
                            if arg.annotation is not None:
                                ann_short = _unparse(arg.annotation).split(".")[-1]
                                if ann_short:
                                    schema_refs.append(ann_short)

                        dep_refs: list[str] = []
                        for default_expr in list(stmt.args.defaults) + [
                            d for d in stmt.args.kw_defaults if d is not None
                        ]:
                            dep_target = _extract_depends_target(default_expr)
                            if dep_target:
                                dep_refs.append(dep_target)

                        nodes.append(
                            Node(
                                id=endpoint_id,
                                kind="Endpoint",
                                name=endpoint_name,
                                qualified_name=endpoint_name,
                                attributes={
                                    "http_method": http_method,
                                    "route_path": route_path,
                                    "handler": f"{mod_name}.{stmt.name}",
                                    "response_model": resp_model,
                                    "status_code": status_code or 200,
                                    "signature": (
                                        f"[{http_method} {route_path}] -> " f"{resp_model or 'Any'}"
                                    ),
                                    "docstring_summary": sanitize_docstring_summary(
                                        ast.get_docstring(stmt)
                                    ),
                                },
                                provenance=prov,
                            )
                        )
                        handler_sym_id = make_symbol_id("py", rel_posix, stmt.name)
                        pending_endpoints.append(
                            (
                                endpoint_id,
                                handler_sym_id,
                                stmt.name,
                                schema_refs,
                                dep_refs,
                                prov,
                            )
                        )

        # Link EXPOSES, VALIDATES_WITH, and DEPENDS_ON edges
        for (
            endpoint_id,
            handler_sym_id,
            _handler_name,
            schema_refs,
            dep_refs,
            prov,
        ) in pending_endpoints:
            edges.append(
                Edge(
                    id=make_edge_id("EXPOSES", handler_sym_id, endpoint_id),
                    kind="EXPOSES",
                    source_id=handler_sym_id,
                    target_id=endpoint_id,
                    provenance=prov,
                )
            )
            for s_ref in sorted(set(schema_refs)):
                if s_ref in schema_id_by_name:
                    s_id = schema_id_by_name[s_ref]
                    edges.append(
                        Edge(
                            id=make_edge_id("VALIDATES_WITH", endpoint_id, s_id),
                            kind="VALIDATES_WITH",
                            source_id=endpoint_id,
                            target_id=s_id,
                            provenance=prov,
                        )
                    )
                    edges.append(
                        Edge(
                            id=make_edge_id("VALIDATES_WITH", handler_sym_id, s_id),
                            kind="VALIDATES_WITH",
                            source_id=handler_sym_id,
                            target_id=s_id,
                            provenance=prov,
                        )
                    )
            for d_ref in sorted(set(dep_refs)):
                if d_ref in symbol_by_short_name:
                    d_id = symbol_by_short_name[d_ref]
                    edges.append(
                        Edge(
                            id=make_edge_id("DEPENDS_ON", endpoint_id, d_id),
                            kind="DEPENDS_ON",
                            source_id=endpoint_id,
                            target_id=d_id,
                            provenance=prov,
                        )
                    )

        return AdapterExtractionResult(
            nodes=tuple(nodes),
            edges=tuple(edges),
            diagnostics=tuple(diagnostics),
        )
