"""LLM JSON 响应解析与本地修复（ADR-0002）。

先直接解析；失败则做一次本地修复（去 markdown code fence、截取首个平衡的
{...} 对象）再解析；仍失败抛 JSONParseError，由 ChainedAIClient 决定 fallback。
"""
from __future__ import annotations

import json


class JSONParseError(ValueError):
    """LLM 响应无法解析为 JSON 对象（含一次本地修复后仍失败）。"""


def parse_json_lenient(text: str) -> dict:
    if text is None:
        raise JSONParseError("empty response")
    candidate = text.strip()
    if not candidate:
        raise JSONParseError("empty response")

    obj = _try_load(candidate)
    if obj is None:
        obj = _try_load(_repair(candidate))
    if obj is None:
        raise JSONParseError("unable to parse JSON object from LLM response")
    return obj


def _try_load(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _repair(text: str) -> str:
    """去掉 markdown fence 并截取首个平衡的 {...} 对象。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        # 去掉首行 ```lang 与末尾 ```
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    if start == -1:
        return stripped
    depth = 0
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    return stripped[start:]
