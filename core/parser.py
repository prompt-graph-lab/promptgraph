import re
from typing import List, Dict, Any

def smart_split(text: str) -> List[str]:
    """
    Split by top-level commas while preserving prompt syntax groups.
    """
    tokens = []
    current = []
    stack = []
    opening_to_closing = {"(": ")", "[": "]", "{": "}"}
    closing = set(opening_to_closing.values())

    for char in text:
        if char in opening_to_closing:
            stack.append(opening_to_closing[char])
        elif char in closing and stack and char == stack[-1]:
            stack.pop()
        elif char == "," and not stack:
            tokens.append("".join(current))
            current = []
            continue

        current.append(char)

    tokens.append("".join(current))
    return tokens


def is_module_marker(token: str) -> bool:
    """
    Detect module markers like <mod:a1b2c3d4>, </mod:a1b2c3d4>,
    or inline tags like <mod:name>content</mod:name>
    """
    token = token.strip()
    if bool(re.fullmatch(r"</?mod:[^>]+>", token)):
        return True
    # Inline check
    if token.startswith("<mod:") and token.endswith(">") and "</mod:" in token:
        # Simple heuristic for inline
        return True
    return False

def extract_mod_info(token: str) -> Dict[str, str]:
    """
    Extract module name and content from a token.
    """
    token = token.strip()
    # Inline: <mod:name>content</mod:name>
    inline_match = re.match(r"<mod:([^>]+)>(.*)</mod:\1>", token)
    if inline_match:
        return {"type": "inline", "name": inline_match.group(1), "content": inline_match.group(2)}
    
    # Opening: <mod:name>
    open_match = re.match(r"<mod:([^>]+)>", token)
    if open_match:
        return {"type": "open", "name": open_match.group(1), "content": ""}
        
    # Closing: </mod:name>
    close_match = re.match(r"</mod:([^>]+)>", token)
    if close_match:
        return {"type": "close", "name": close_match.group(1), "content": ""}
        
    return {"type": "none", "name": "", "content": token}


def is_structural_mod_marker(token: str) -> bool:
    """
    Detect structural markers (open/close) but NOT inline ones.
    """
    info = extract_mod_info(token)
    return info["type"] in ("open", "close")

def parse_prompt(text: str) -> List[str]:
    """
    プロンプト文字列をカンマ区切りでトークン化する（カッコ内のカンマは無視）。
    モジュールマーカーはグラフノードとしてパースしないよう除外する。
    """
    tokens = smart_split(text)
    return [
        t.strip()
        for t in tokens
        if t.strip()
    ]

def extract_node_metadata(token: str) -> Dict[str, Any]:
    """
    トークンからフレーズ、重みなどのメタデータを抽出する。
    例: "(smile:1.2)" -> {phrase: ["smile"], weight: 1.2, original: "(smile:1.2)", group: "expression"}
    """
    orig_token = token.strip()
    token = orig_token
    
    # Strip inline mod if any
    info = extract_mod_info(token)
    if info["type"] == "inline":
        token = info["content"].strip()
    elif info["type"] in ("open", "close"):
        # Structural markers shouldn't really be passed here, but handle just in case
        token = ""

    weight = 1.0
    phrase_text = token
    
    # 重みパターンの検出 (word:weight)
    match = re.match(r"^\((.+):([\d\.]+)\)$", token)
    if match:
        phrase_text = match.group(1).strip()
        try:
            weight = float(match.group(2))
        except ValueError:
            weight = 1.0
            
    phrase_list = phrase_text.split()
    
    group = "default"
    expression_words = {"smile", "angry", "sad", "laughing", "crying"}
    if any(w.lower() in expression_words for w in phrase_list):
        group = "expression"
            
    return {
        "phrase": phrase_list,
        "weight": weight,
        "original": orig_token,
        "base_word": phrase_text,
        "group": group
    }
