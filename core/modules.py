from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List

from core.parser import extract_mod_info, parse_prompt


MODULE_GRAPH_TYPE = "module_graph"
MODULE_GRAPH_VERSION = 1

DEFAULT_BOUNDARY_POLICY = {
    "preserve_connected_extras": True,
    "allow_split": True,
    "allow_merge": True,
}

DEFAULT_REPLACEMENT_POLICY = {
    "mode": "flatten_current",
    "future_modes": [
        "replace_exact_subgraph",
        "replace_core_preserve_extras",
        "replace_including_optional",
        "map_variant",
    ],
}


def make_module_id(module_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", (module_name or "").strip()).strip("_")
    if not slug:
        slug = "untitled"
    return slug if slug.startswith("module_") else f"module_{slug}"


def _default_metadata(module_role: str = "generic") -> Dict[str, Any]:
    return {
        "role": module_role or "generic",
        "tags": [],
        "notes": "",
    }


def _ordered_sequence_edges(nodes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {
            "source": nodes[idx]["id"],
            "target": nodes[idx + 1]["id"],
            "kind": "sequence",
        }
        for idx in range(len(nodes) - 1)
    ]


def _normalize_graph_nodes(raw_nodes: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_nodes, list):
        return []

    nodes: List[Dict[str, Any]] = []
    seen_ids = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue

        node = dict(raw_node)
        node_id = str(node.get("id", "")).strip()
        if not node_id or node_id in seen_ids:
            continue

        kind = node.get("kind")
        if kind == "token":
            text = str(node.get("text", "")).strip()
            if not text:
                continue
            node["id"] = node_id
            node["text"] = text
            nodes.append(node)
            seen_ids.add(node_id)
            continue

        if kind == "module_ref":
            module_name = str(node.get("module_name", "")).strip()
            ref = str(node.get("ref", "")).strip()
            if not module_name or not ref:
                continue
            node["id"] = node_id
            node["module_name"] = module_name
            node["ref"] = ref
            nodes.append(node)
            seen_ids.add(node_id)

    return nodes


def _normalize_graph_edges(raw_edges: Any, nodes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if not isinstance(raw_edges, list):
        return _ordered_sequence_edges(nodes)

    node_ids = {node["id"] for node in nodes}
    edges: List[Dict[str, str]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        source = str(raw_edge.get("source", "")).strip()
        target = str(raw_edge.get("target", "")).strip()
        if source not in node_ids or target not in node_ids:
            continue
        edges.append({
            "source": source,
            "target": target,
            "kind": str(raw_edge.get("kind", "sequence") or "sequence"),
        })
    return edges


def token_list_to_module_graph(
    module_name: str,
    tokens: List[str],
    module_type: str = "generic",
    module_id: str | None = None,
) -> Dict[str, Any]:
    """Convert a flat token list into the v1 nested module graph shape.

    TODO: Replace Core, Preserve Extras should use node roles and policies here.
    TODO: Optional / Variant Modules should attach variants as related refs.
    TODO: Connected Module extraction should create module_ref nodes from ranges.
    TODO: Split Module should preserve deterministic node ids for unchanged nodes.
    TODO: Merge Modules should reconcile child and related refs without duplication.
    TODO: Module boundary editor should edit boundary_policy instead of raw tags.
    """
    nodes: List[Dict[str, Any]] = []
    child_refs: List[str] = []

    for idx, raw_token in enumerate(tokens or [], start=1):
        token = str(raw_token).strip()
        if not token:
            continue

        info = extract_mod_info(token)
        if info["type"] == "open":
            ref = make_module_id(info["name"])
            nodes.append({
                "id": f"m{idx}",
                "kind": "module_ref",
                "ref": ref,
                "module_name": info["name"],
                "role": "child",
            })
            if ref not in child_refs:
                child_refs.append(ref)
            continue

        if info["type"] == "inline":
            content = info["content"].strip()
            if content:
                nodes.append({
                    "id": f"n{idx}",
                    "kind": "token",
                    "text": content,
                    "role": "core",
                })
            continue

        if info["type"] == "close":
            continue

        nodes.append({
            "id": f"n{idx}",
            "kind": "token",
            "text": token,
            "role": "core",
        })

    return {
        "id": module_id or make_module_id(module_name),
        "name": module_name,
        "type": MODULE_GRAPH_TYPE,
        "version": MODULE_GRAPH_VERSION,
        "nodes": nodes,
        "edges": _ordered_sequence_edges(nodes),
        "child_module_refs": child_refs,
        "related_module_refs": [],
        "metadata": _default_metadata(module_type),
        "boundary_policy": deepcopy(DEFAULT_BOUNDARY_POLICY),
        "replacement_policy": deepcopy(DEFAULT_REPLACEMENT_POLICY),
    }


def create_blank_module_graph(
    module_name: str,
    text_or_tokens: str | List[str] | None = None,
    module_type: str = "generic",
) -> Dict[str, Any]:
    if isinstance(text_or_tokens, list):
        tokens = [str(token).strip() for token in text_or_tokens if str(token).strip()]
    else:
        normalized_text = re.sub(r"[\r\n]+", ", ", text_or_tokens or "")
        tokens = parse_prompt(normalized_text)
    return token_list_to_module_graph(module_name, tokens, module_type)


def flatten_module_graph_to_tokens(module_graph: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    for node in (module_graph or {}).get("nodes", []):
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "token":
            text = str(node.get("text", "")).strip()
            if text:
                tokens.append(text)
        elif node.get("kind") == "module_ref":
            module_name = str(node.get("module_name", "")).strip()
            if module_name:
                tokens.append(f"<mod:{module_name}>")
    return tokens


def validate_module_graph(module_graph: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(module_graph, dict):
        return ["Module graph must be a JSON object."]

    if module_graph.get("type") != MODULE_GRAPH_TYPE:
        errors.append("Module graph type must be module_graph.")
    if module_graph.get("version") != MODULE_GRAPH_VERSION:
        errors.append("Module graph version must be 1.")
    if not str(module_graph.get("id", "")).strip():
        errors.append("Module graph id is required.")
    if not str(module_graph.get("name", "")).strip():
        errors.append("Module graph name is required.")

    nodes = module_graph.get("nodes", [])
    edges = module_graph.get("edges", [])
    if not isinstance(nodes, list):
        errors.append("Module graph nodes must be a list.")
        nodes = []
    if not isinstance(edges, list):
        errors.append("Module graph edges must be a list.")
        edges = []

    node_ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("Module graph nodes must be objects.")
            continue
        node_id = str(node.get("id", "")).strip()
        if not node_id:
            errors.append("Module graph node id is required.")
        elif node_id in node_ids:
            errors.append(f"Duplicate module graph node id: {node_id}.")
        node_ids.add(node_id)

        kind = node.get("kind")
        if kind == "token":
            if not str(node.get("text", "")).strip():
                errors.append(f"Token node {node_id or '<missing>'} requires text.")
        elif kind == "module_ref":
            if not str(node.get("ref", "")).strip():
                errors.append(f"Module reference node {node_id or '<missing>'} requires ref.")
            if not str(node.get("module_name", "")).strip():
                errors.append(f"Module reference node {node_id or '<missing>'} requires module_name.")
        else:
            errors.append(f"Unknown module graph node kind: {kind}.")

    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("Module graph edges must be objects.")
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if source not in node_ids:
            errors.append(f"Module graph edge source is missing: {source}.")
        if target not in node_ids:
            errors.append(f"Module graph edge target is missing: {target}.")

    return errors


def normalize_module_graph(
    module_name: str,
    entry: Dict[str, Any] | str | None,
    module_type: str = "generic",
) -> Dict[str, Any]:
    if isinstance(entry, dict) and isinstance(entry.get("graph"), dict):
        graph = deepcopy(entry["graph"])
        graph.setdefault("id", make_module_id(module_name))
        graph.setdefault("name", module_name)
        graph.setdefault("type", MODULE_GRAPH_TYPE)
        graph.setdefault("version", MODULE_GRAPH_VERSION)
        graph["nodes"] = _normalize_graph_nodes(graph.get("nodes"))
        graph["edges"] = _normalize_graph_edges(graph.get("edges"), graph["nodes"])
        if not isinstance(graph.get("child_module_refs"), list):
            graph["child_module_refs"] = []
        if not isinstance(graph.get("related_module_refs"), list):
            graph["related_module_refs"] = []
        if not isinstance(graph.get("metadata"), dict):
            graph["metadata"] = _default_metadata(module_type)
        if not isinstance(graph.get("boundary_policy"), dict):
            graph["boundary_policy"] = deepcopy(DEFAULT_BOUNDARY_POLICY)
        if not isinstance(graph.get("replacement_policy"), dict):
            graph["replacement_policy"] = deepcopy(DEFAULT_REPLACEMENT_POLICY)
        return graph

    body = entry.get("body", "") if isinstance(entry, dict) else entry
    return create_blank_module_graph(module_name, body or "", module_type)
