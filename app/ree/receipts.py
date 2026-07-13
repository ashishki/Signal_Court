"""REE receipt parsing and hash recomputation.

A REE receipt (16-field JSON) records a reproducible inference run. The
receipt_hash is the master validation hash over five component hashes:
commit_hash, config_hash, prompt_hash, parameters_hash, tokens_hash.

Gensyn REE v0.2.0 computes receipt_hash as SHA-256 over the pipe-delimited
component hashes, returned with a "sha256:" prefix.

Local parsing and content/hash recomputation are not the same as REE-side
verification. receipt_status="validated" means the embedded prompt,
parameters, and text output match their component hashes and the master hash
recomputed correctly. receipt_status="verified" is reserved for full
re-execution. receipt_status="parsed" means the receipt is structurally valid
but one or more hashes did not recompute under a supported SDK algorithm.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ReeReceipt(BaseModel):
    """Parsed view of a Gensyn REE receipt JSON document (16-field schema)."""

    model_name: str = Field(min_length=1)
    commit_hash: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    prompt: str = ""
    prompt_hash: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    parameters_hash: str = Field(min_length=1)
    tokens_hash: str = Field(min_length=1)
    token_count: int = Field(ge=0, default=0)
    finish_reason: str = ""
    text_output: str = ""
    device_type: str = ""
    device_name: str = ""
    receipt_hash: str = Field(min_length=1)
    version: str = ""
    ree_version: str = ""


def parse_ree_receipt(
    source: str | Path | bytes | bytearray | dict[str, Any],
) -> ReeReceipt:
    """Load a REE receipt from a path, raw bytes, JSON text, or a dict."""
    if isinstance(source, ReeReceipt):
        return source
    if isinstance(source, dict):
        data = source
    elif isinstance(source, (bytes, bytearray)):
        data = json.loads(bytes(source).decode("utf-8"))
    elif isinstance(source, Path):
        data = json.loads(source.read_text(encoding="utf-8"))
    elif isinstance(source, str):
        stripped = source.lstrip()
        if stripped.startswith("{"):
            data = json.loads(source)
        else:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        raise TypeError(f"Unsupported REE receipt source type: {type(source)!r}")
    data = _normalize_receipt_data(data)
    return ReeReceipt.model_validate(data)


def compute_receipt_hash(
    *,
    commit_hash: str,
    config_hash: str,
    prompt_hash: str,
    parameters_hash: str,
    tokens_hash: str,
) -> str:
    """Recompute the Gensyn receipt hash from the five component hashes.

    Field order follows the Gensyn SDK implementation: commit, config, prompt,
    parameters, tokens. Components are joined with "|" and hashed with SHA-256.
    """
    components = "|".join(
        [
            commit_hash,
            config_hash,
            prompt_hash,
            parameters_hash,
            tokens_hash,
        ]
    )
    return f"sha256:{hashlib.sha256(components.encode('utf-8')).hexdigest()}"


def _normalize_receipt_data(data: dict[str, Any]) -> dict[str, Any]:
    """Map real nested Gensyn receipt JSON into the internal flat model."""
    if "model_name" in data:
        return data

    model = data.get("model")
    input_data = data.get("input")
    output = data.get("output")
    execution = data.get("execution")
    hashes = data.get("hashes")
    if not all(
        isinstance(section, dict)
        for section in (model, input_data, output, execution, hashes)
    ):
        return data

    return {
        "model_name": model.get("name", ""),
        "commit_hash": model.get("commit_hash", ""),
        "config_hash": model.get("config_hash", ""),
        "prompt": input_data.get("prompt", ""),
        "prompt_hash": input_data.get("prompt_hash", ""),
        "parameters": input_data.get("parameters") or {},
        "parameters_hash": input_data.get("parameters_hash", ""),
        "tokens_hash": output.get("tokens_hash", ""),
        "token_count": output.get("token_count", 0),
        "finish_reason": output.get("finish_reason", ""),
        "text_output": output.get("text_output", ""),
        "device_type": execution.get("device_type", ""),
        "device_name": execution.get("device_name", ""),
        "receipt_hash": hashes.get("receipt_hash", ""),
        "version": data.get("version", ""),
        "ree_version": data.get("ree_version", ""),
    }
