"""JSON exporter for canonical graph and manifest bundles."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from context_archive.lock import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.model.graph import CanonicalGraph
    from context_archive.model.manifest import Manifest


def render_export_bundle_json(manifest: Manifest, graph: CanonicalGraph) -> str:
    """Serialize both manifest and canonical graph into a single deterministic JSON bundle."""
    manifest_obj = json.loads(manifest.to_deterministic_json())
    graph_obj = json.loads(graph.to_deterministic_json())
    bundle = {
        "schema_version": "1.0.0",
        "manifest": manifest_obj,
        "graph": graph_obj,
    }
    return json.dumps(bundle, indent=2, sort_keys=True) + "\n"


def export_canonical_json(
    *,
    manifest: Manifest,
    graph: CanonicalGraph,
    output_path: Path | None = None,
) -> str:
    """Export canonical bundle JSON, writing atomically to output_path if specified."""
    rendered = render_export_bundle_json(manifest, graph)
    if output_path is not None:
        atomic_write_text(output_path, rendered)
    return rendered
