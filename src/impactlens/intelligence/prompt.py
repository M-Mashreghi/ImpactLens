"""Versioned prompt construction with strict untrusted-content delimiters."""

from __future__ import annotations

import json
from importlib import resources

from impactlens.intelligence.schema import json_schema

PROMPT_VERSION = "prompt-v1"
START = "<<<ARTICLE_START>>>"
END = "<<<ARTICLE_END>>>"


def system_prompt() -> str:
    return (resources.files("impactlens.intelligence") / "prompts" / "system_v1.txt").read_text("utf-8")


def _neutralize(text: str) -> str:
    # The article must not be able to close its own data block.
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def user_prompt(title: str, text: str, published_at: str | None, source_name: str) -> str:
    schema = json.dumps(json_schema(), separators=(",", ":"), sort_keys=True)
    return (
        f"JSON schema for your response:\n{schema}\n\n"
        f"Article metadata (trusted): source={source_name!r}, published_at={published_at or 'unknown'}\n\n"
        f"{START}\nTITLE: {_neutralize(title)}\n\n{_neutralize(text)}\n{END}\n\n"
        "Return only the JSON object."
    )
