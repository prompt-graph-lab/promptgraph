from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Any
import copy

@dataclass
class PromptLine:
    id: str
    original_file_name: str
    original_index: int
    current_index: int
    original_text: str
    current_text: str
    tokens: List[str]
    negative_prompt: str = ""
    source_generation_info: Dict[str, Any] = field(default_factory=dict)
    lineage_info: Dict[str, Any] = field(default_factory=dict)
    node_path: List[str] = field(default_factory=list)
    edited: bool = False
    deleted: bool = False
    duplicated_from: Optional[str] = None
    image_path: Optional[str] = None
    generated_image_path: Optional[str] = None
    selected_candidate_path: Optional[str] = None
    generated_candidates: List[Dict[str, Any]] = field(default_factory=list)
    gallery_variants: List[Dict[str, Any]] = field(default_factory=list)
    line_type: Optional[str] = None
    separator_label: Optional[str] = None
    separator_color: Optional[str] = None
    workbench_source_line_id: Optional[str] = None
    workbench_title: Optional[str] = None
    workbench_note: Optional[str] = None
    workbench_status: Optional[str] = None

@dataclass
class PromptNode:
    id: str
    word: str
    depth: int
    count: int = 1
    prompt_line_ids: Set[str] = field(default_factory=set)
    prev_node_ids: Set[str] = field(default_factory=set)
    next_node_ids: Set[str] = field(default_factory=set)
    
    phrase: List[str] = field(default_factory=list)
    group: str = "default"
    weight: float = 1.0
    original: str = ""
    display: str = ""

    def __post_init__(self):
        if not self.phrase:
            self.phrase = self.word.split() if self.word else []
        if not self.original:
            self.original = self.word
        if not self.display:
            self.display = self.original

@dataclass
class Project:
    source_directory: str = ""
    prompt_lines: List[PromptLine] = field(default_factory=list)
    line_groups: Dict[str, List[str]] = field(default_factory=dict)
    module_library: Dict[str, Any] = field(default_factory=dict)
    node_attribute_labels: Dict[str, str] = field(default_factory=dict)
    custom_attribute_labels: List[str] = field(default_factory=list)
    attribute_label_usage_counts: Dict[str, int] = field(default_factory=dict)
    attribute_groups: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    project_metadata: Dict[str, Any] = field(default_factory=dict)
    route_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    line_map: Dict[str, PromptLine] = field(default_factory=dict)
    nodes: Dict[str, PromptNode] = field(default_factory=dict)
    edges: List[tuple] = field(default_factory=list)  # (source_id, target_id)
    node_freq: Dict[str, int] = field(default_factory=dict)
    phrase_freq: Dict[str, int] = field(default_factory=dict)
    global_group_freq: Dict[str, Dict[str, int]] = field(default_factory=dict)
    merge_by_word_only: bool = True
    
    def clone(self) -> "Project":
        # Undo/Redo用のディープコピー
        return copy.deepcopy(self)
