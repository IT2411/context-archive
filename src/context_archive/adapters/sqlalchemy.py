"""SQLAlchemy and SQLModel database entity extractor (SRS FR-06)."""

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

EXTRACTOR_ID = "sqlalchemy_entity:1.0"
ORM_BASE_NAMES = frozenset({"DeclarativeBase", "Base", "Model"})


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return ""


def _extract_tablename(class_stmt: ast.ClassDef) -> str | None:
    """Return string value of `__tablename__ = '...'` if present on a class."""
    for item in class_stmt.body:
        if isinstance(item, ast.Assign):
            for t in item.targets:
                if (
                    isinstance(t, ast.Name)
                    and t.id == "__tablename__"
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)
                ):
                    return item.value.value
    return None


class SqlAlchemyEntityExtractor:
    """Static AST extractor for SQLAlchemy declarative models and database tables."""

    @property
    def adapter_id(self) -> str:
        return EXTRACTOR_ID

    def can_handle(self, scanned_file: ScannedFile) -> bool:
        return scanned_file.language == "python" and scanned_file.category == "source_code"

    def extract_repository(
        self,
        repo_root: Path,
        files: tuple[ScannedFile, ...] | list[ScannedFile],
    ) -> AdapterExtractionResult:
        """Extract DataEntity nodes and link READS/WRITES edges from referencing functions."""
        nodes: list[Node] = []
        edges: list[Edge] = []
        diagnostics: list[Diagnostic] = []

        py_files = sorted(
            (f for f in files if self.can_handle(f)),
            key=lambda item: item.path,
        )

        entity_id_by_class_name: dict[str, str] = {}
        parsed_trees: list[tuple[str, ast.Module]] = []

        # Pass 1: Discover DataEntity classes
        for scanned in py_files:
            rel_posix = normalize_posix_path(scanned.path)
            try:
                source_text = (repo_root / rel_posix).read_text(encoding="utf-8")
                tree = ast.parse(source_text, filename=rel_posix)
            except (OSError, SyntaxError, ValueError):
                continue

            parsed_trees.append((rel_posix, tree))
            mod_name = compute_python_module_name(rel_posix)

            for stmt in tree.body:
                if not isinstance(stmt, ast.ClassDef):
                    continue
                if stmt.name in ORM_BASE_NAMES:
                    continue

                tablename = _extract_tablename(stmt)
                base_names = {_unparse(b).split(".")[-1] for b in stmt.bases}
                if tablename is None and not (base_names & ORM_BASE_NAMES):
                    continue

                columns: list[dict[str, str]] = []
                for item in stmt.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        col_name = item.target.id
                        if col_name.startswith("_"):
                            continue
                        col_type = _unparse(item.annotation)
                        columns.append({"name": col_name, "type": col_type})
                    elif isinstance(item, ast.Assign):
                        for t in item.targets:
                            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                                val_str = _unparse(item.value)
                                if "Column" in val_str or "mapped_column" in val_str:
                                    columns.append({"name": t.id, "type": val_str})

                line_start = getattr(stmt, "lineno", 1)
                line_end = getattr(stmt, "end_lineno", line_start) or line_start
                entity_id = make_symbol_id("entity:py", rel_posix, stmt.name)
                prov = Provenance(
                    source_path=rel_posix,
                    line_start=line_start,
                    line_end=line_end,
                    extractor=EXTRACTOR_ID,
                    evidence_kind="deterministic",
                    confidence="high",
                )
                effective_table = tablename or stmt.name.lower()
                col_summary = ", ".join(f"{c['name']}: {c['type']}" for c in columns)
                nodes.append(
                    Node(
                        id=entity_id,
                        kind="DataEntity",
                        name=stmt.name,
                        qualified_name=f"{mod_name}.{stmt.name}",
                        attributes={
                            "table_name": effective_table,
                            "columns": columns,
                            "signature": f"table='{effective_table}' ({col_summary})",
                            "docstring_summary": sanitize_docstring_summary(
                                ast.get_docstring(stmt)
                            ),
                        },
                        provenance=prov,
                    )
                )
                entity_id_by_class_name[stmt.name] = entity_id

        if not entity_id_by_class_name:
            return AdapterExtractionResult()

        # Pass 2: Link functions/methods referencing DataEntity classes via READS/WRITES
        for rel_posix, tree in parsed_trees:
            for stmt in tree.body:
                if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                    func_id = make_symbol_id("py", rel_posix, stmt.name)
                    line_start = getattr(stmt, "lineno", 1)
                    line_end = getattr(stmt, "end_lineno", line_start) or line_start
                    referenced_entities: set[str] = set()
                    for child in ast.walk(stmt):
                        if isinstance(child, ast.Name) and child.id in entity_id_by_class_name:
                            referenced_entities.add(entity_id_by_class_name[child.id])

                    is_write = stmt.name.startswith(("create_", "update_", "delete_", "save_"))
                    edge_kind = "WRITES" if is_write else "READS"
                    prov = Provenance(
                        source_path=rel_posix,
                        line_start=line_start,
                        line_end=line_end,
                        extractor=EXTRACTOR_ID,
                        evidence_kind="deterministic",
                        confidence="high",
                    )
                    for ent_id in sorted(referenced_entities):
                        edges.append(
                            Edge(
                                id=make_edge_id(edge_kind, func_id, ent_id),
                                kind=edge_kind,
                                source_id=func_id,
                                target_id=ent_id,
                                provenance=prov,
                            )
                        )

        return AdapterExtractionResult(
            nodes=tuple(nodes),
            edges=tuple(edges),
            diagnostics=tuple(diagnostics),
        )
