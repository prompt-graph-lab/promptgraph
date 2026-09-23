"""Pure A1111 parameters interpretation for Project image metadata imports.

Keep raw text, section detection, quoted chunks and parameter values in their
legacy form. Image acquisition, metadata-source precedence, Project mutation
and persistence remain in core.io.
"""

A1111_PARAM_START_KEYS = (
    "Steps",
    "Sampler",
    "Schedule type",
    "CFG scale",
    "Seed",
    "Size",
    "Model hash",
    "Model",
    "Denoising strength",
    "Clip skip",
    "RNG",
    "Hires Module 1",
    "Hires CFG Scale",
    "Hires upscale",
    "Hires steps",
    "Hires upscaler",
    "Lora hashes",
    "Version",
    "Module 1",
)


def _looks_like_a1111_param_line(line: str) -> bool:
    stripped = line.strip()
    return any(stripped.startswith(f"{key}:") for key in A1111_PARAM_START_KEYS)


def _split_a1111_sections(parameters: str) -> tuple[str, str, str]:
    text = parameters.replace("\r\n", "\n").replace("\r", "\n")
    marker = "\nNegative prompt:"
    if marker in text:
        positive, remainder = text.split(marker, 1)
        remainder_lines = remainder.split("\n")
        params_index = next(
            (index for index, line in enumerate(remainder_lines) if _looks_like_a1111_param_line(line)),
            None,
        )
        if params_index is None:
            return positive.strip(), remainder.strip(), ""
        negative = "\n".join(remainder_lines[:params_index]).strip()
        raw_generation_params = "\n".join(remainder_lines[params_index:]).strip()
        return positive.strip(), negative, raw_generation_params

    lines = text.split("\n")
    params_index = next(
        (index for index, line in enumerate(lines) if _looks_like_a1111_param_line(line)),
        None,
    )
    if params_index is None:
        return text.strip(), "", ""
    positive = "\n".join(lines[:params_index]).strip()
    raw_generation_params = "\n".join(lines[params_index:]).strip()
    return positive, "", raw_generation_params


def _split_a1111_param_chunks(raw_generation_params: str) -> list[str]:
    chunks = []
    current = []
    quote_char = ""
    escape_next = False
    for char in raw_generation_params.replace("\n", ", "):
        if escape_next:
            current.append(char)
            escape_next = False
            continue
        if char == "\\" and quote_char:
            current.append(char)
            escape_next = True
            continue
        if char in ("'", '"'):
            if quote_char == char:
                quote_char = ""
            elif not quote_char:
                quote_char = char
            current.append(char)
            continue
        if char == "," and not quote_char:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            continue
        current.append(char)

    chunk = "".join(current).strip()
    if chunk:
        chunks.append(chunk)
    return chunks


def _parse_a1111_generation_params(raw_generation_params: str) -> dict:
    params = {}
    current_key = ""
    for chunk in _split_a1111_param_chunks(raw_generation_params):
        if ":" not in chunk:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        key, value = chunk.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            if current_key:
                params[current_key] = f"{params[current_key]}, {chunk}".strip()
            continue
        params[key] = value
        current_key = key
    return params


def _parse_a1111_parameters(parameters: str) -> dict:
    if not isinstance(parameters, str) or not parameters.strip():
        return {}
    prompt_text, negative_prompt, raw_generation_params = _split_a1111_sections(parameters)
    return {
        "source_engine": "webui_a1111",
        "raw_parameters": parameters,
        "prompt_text": prompt_text,
        "negative_prompt": negative_prompt,
        "raw_generation_params": raw_generation_params,
        "generation_params": _parse_a1111_generation_params(raw_generation_params),
    }


def _extract_a1111_prompt_fields(parameters: str) -> tuple[str, str]:
    parsed = _parse_a1111_parameters(parameters)
    return parsed.get("prompt_text", ""), parsed.get("negative_prompt", "")
