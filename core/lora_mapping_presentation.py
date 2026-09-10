"""Read-only LoRA mapping option labels, reference grouping and strength defaults."""


def _lora_loader_candidate_label(candidate: dict) -> str:
    missing = candidate.get("missing_fields") or []
    missing_text = f" - missing: {', '.join(missing)}" if missing else ""
    return (
        f"{candidate['node_id']} - {candidate['class_type']}"
        f" - {candidate.get('lora_name', '')}"
        f" - model={candidate.get('strength_model', '')}"
        f" - clip={candidate.get('strength_clip', '')}"
        f"{missing_text}"
    )


def _lora_ref_weight_label(reference: dict) -> str:
    model_weight = reference.get("model_weight") or ""
    clip_weight = reference.get("clip_weight") or ""
    if model_weight and clip_weight:
        return f"{model_weight}/{clip_weight}"
    return model_weight or clip_weight or ""


def _dedupe_lora_reference_options(references: list[dict]) -> list[dict]:
    grouped = {}
    for ref in references:
        name = ref.get("name", "")
        if not name:
            continue
        option = grouped.setdefault(name, {
            "name": name,
            "weights": [],
            "model_weight": "",
            "clip_weight": "",
        })
        weight_label = _lora_ref_weight_label(ref)
        if weight_label and weight_label not in option["weights"]:
            option["weights"].append(weight_label)
        if not option["model_weight"] and ref.get("model_weight"):
            option["model_weight"] = ref["model_weight"]
        if not option["clip_weight"] and ref.get("clip_weight"):
            option["clip_weight"] = ref["clip_weight"]
    return sorted(grouped.values(), key=lambda item: item["name"].lower())


def _lora_reference_option_label(option: dict) -> str:
    weights = ", ".join(option.get("weights") or [])
    return f"{option['name']} - weights: {weights}" if weights else option["name"]


def _safe_float_or_default(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _lora_strength_defaults(model_weight="", clip_weight="") -> tuple[float, float]:
    model = _safe_float_or_default(model_weight, 1.0)
    clip = _safe_float_or_default(clip_weight, model)
    return model, clip


def _lora_reference_signature(references: list[dict]) -> tuple:
    return tuple(sorted((ref.get("line_id", ""), ref.get("raw", "")) for ref in references))


def _mapped_lora_option_label(option: dict) -> str:
    weights = ", ".join(option.get("weights") or [])
    return f"{option['label']} - weights: {weights}" if weights else option["label"]


def _key_fragment(value) -> str:
    text = str(value or "")
    return "".join(ch if ch.isalnum() else "_" for ch in text)[:80] or "empty"
