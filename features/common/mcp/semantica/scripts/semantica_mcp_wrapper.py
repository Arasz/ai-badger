#!/usr/bin/env python3
"""Wrapper that patches semantica's broken export_graph JSON branch.

Upstream 0.6.5-0.6.6: _tool_export_graph calls JSONExporter().export(graph)
without file_path, but export() requires it.  This wrapper monkeypatches the
json branch to convert the graph to a dict and write to a tempfile.

Launch: python semantica_mcp_wrapper.py  (or via Hermes MCP config)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def _patched_tool_export_graph(args: dict) -> dict:
    """Drop-in replacement for semantica.mcp_server._tool_export_graph."""
    fmt = args.get("format", "json-ld")
    try:
        from semantica.mcp_server import _get_graph
        from semantica.export import RDFExporter, JSONExporter

        graph = _get_graph()
        if fmt in ("turtle", "ttl", "nt", "xml", "json-ld"):
            result = RDFExporter().export_to_rdf(graph, format=fmt)
        else:
            # The bug: JSONExporter().export(graph) needs file_path.
            # Convert graph to dict first (ContextGraph is not JSON-serializable),
            # then write to a tempfile and read back.
            graph_dict = graph.to_dict()
            exporter = JSONExporter()
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w"
            ) as tmp:
                tmp_path = tmp.name
            try:
                exporter.export(graph_dict, file_path=tmp_path)
                result = Path(tmp_path).read_text(encoding="utf-8")
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        return {"format": fmt, "data": result}
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    """Patch the handler then start the stdio MCP server."""
    import semantica.mcp_server as _server

    _server._tool_export_graph = _patched_tool_export_graph
    _server.main()


if __name__ == "__main__":
    main()
