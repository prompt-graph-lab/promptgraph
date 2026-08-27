from typing import List, Dict, Set, Tuple
from core.project import Project, PromptLine, PromptNode
from core.parser import extract_node_metadata, is_module_marker, is_structural_mod_marker
import hashlib

def _is_graph_prompt_line(line: PromptLine) -> bool:
    return not getattr(line, "deleted", False) and getattr(line, "line_type", None) not in {"separator", "workbench"}

def make_node_id(depth: int, phrase: list[str], weight: float, group: str) -> str:
    key = f"{depth}|{' '.join(sorted(phrase))}|{group}"
    return "n_" + hashlib.md5(key.encode()).hexdigest()[:8]

def build_graph(project: Project, max_depth: int = None) -> Project:
    MAX_NODES = 300
    # v1: module_library references expand for export/active prompts, while graph nodes use stored line tokens.
    
    # Pass 0: Compute FULL frequency BEFORE any filtering (max_depth or top_nodes)
    phrase_freq = {}
    global_group_freq = {}
    project.line_map = {}
    
    for line in project.prompt_lines:
        project.line_map[line.id] = line
        if not _is_graph_prompt_line(line):
            continue
            
        for word in line.tokens:
            if is_structural_mod_marker(word):
                continue
                
            meta = extract_node_metadata(word)
            group = meta.get("group", "default")
            
            if meta["phrase"]:
                phrase = meta["phrase"]
            else:
                phrase = [meta["base_word"]]
                
            phrase_key = " ".join(sorted(phrase))
            phrase_freq[phrase_key] = phrase_freq.get(phrase_key, 0) + 1
            
            if group not in global_group_freq:
                global_group_freq[group] = {}
            global_group_freq[group][phrase_key] = global_group_freq[group].get(phrase_key, 0) + 1
            
    project.phrase_freq = phrase_freq
    project.global_group_freq = global_group_freq
    
    # Pass 1: Pre-count node frequencies for graph nodes
    node_freq: Dict[str, int] = {}
    
    for line in project.prompt_lines:
        if not _is_graph_prompt_line(line):
            continue
        for depth, word in enumerate(line.tokens):
            if max_depth is not None and depth > max_depth:
                break
            
            if is_structural_mod_marker(word):
                continue
                
            meta = extract_node_metadata(word)
            group = meta.get("group", "default")
            
            if not meta["phrase"]:
                meta["phrase"] = [meta["base_word"]]
                
            if getattr(project, "merge_by_word_only", False):
                node_id = f"w_{' '.join(sorted(meta['phrase']))}_{group}"
            else:
                node_id = make_node_id(depth, meta["phrase"], meta["weight"], group)
                
            node_freq[node_id] = node_freq.get(node_id, 0) + 1

    project.node_freq = node_freq

    # Select top N nodes
    top_nodes = set(sorted(node_freq.keys(), key=lambda k: node_freq[k], reverse=True)[:MAX_NODES])

    # Pass 2: Build graph with selected nodes
    nodes: Dict[str, PromptNode] = {}
    edges: Set[Tuple[str, str]] = set()
    edge_counts: Dict[Tuple[str, str], int] = {}

    for line in project.prompt_lines:
        if not _is_graph_prompt_line(line):
            continue
            
        prev_node_id = None
        line.node_path = []
        
        for depth, word in enumerate(line.tokens):
            if max_depth is not None and depth > max_depth:
                break
                
            if is_structural_mod_marker(word):
                line.node_path.append(word)
                continue
                
            meta = extract_node_metadata(word)
            group = meta.get("group", "default")
            
            if not meta["phrase"]:
                meta["phrase"] = [meta["base_word"]]
            
            if getattr(project, "merge_by_word_only", False):
                node_id = f"w_{' '.join(sorted(meta['phrase']))}_{group}"
            else:
                node_id = make_node_id(depth, meta["phrase"], meta["weight"], group)
            
            # Maintain full node_path alignment
            line.node_path.append(node_id)
            
            if node_id not in top_nodes:
                continue
            
            if node_id not in nodes:
                nodes[node_id] = PromptNode(
                    id=node_id,
                    word=word,
                    depth=depth,
                    count=0,
                    phrase=meta["phrase"],
                    group=group,
                    weight=meta["weight"],
                    original=meta["original"],
                    display=meta["base_word"]
                )
            
            node = nodes[node_id]
            node.count += 1
            node.prompt_line_ids.add(line.id)
            
            if prev_node_id and prev_node_id != node_id and prev_node_id in top_nodes:
                node.prev_node_ids.add(prev_node_id)
                nodes[prev_node_id].next_node_ids.add(node_id)
                edge = (prev_node_id, node_id)
                edges.add(edge)
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
            
            prev_node_id = node_id

    # Filter edges by top frequencies for clarity
    if len(nodes) > 100:
        sorted_edges = sorted(edge_counts.keys(), key=lambda e: edge_counts[e], reverse=True)
        top_edges = set(sorted_edges[:400])
        edges = {e for e in edges if e in top_edges}

    project.nodes = nodes
    project.edges = list(edges)
    return project
