"""Nebius Token Factory client with fallback/mock capability."""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from openai import OpenAI


# Load .env if present
_env_path = Path(".env")
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())


DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
LEVEL_2_DEFAULT_MODEL = os.environ.get("LEVEL_2_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
LEVEL_1_DEFAULT_MODEL = os.environ.get("LEVEL_1_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")


def clean_model_output(text: str) -> str:
    """Strips <think> tags and XML metadata from model completions."""
    import re
    # Remove complete <think>...</think> blocks
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text)
    # If the response was truncated while still inside a <think> tag
    cleaned = re.sub(r"^<think>[\s\S]*", "", cleaned)
    return cleaned.strip()


class NebiusClient:
    """Wrapper around Nebius Token Factory OpenAI-compatible API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        self.base_url = base_url or os.environ.get("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL)
        self.mock_mode = mock_mode or (not self.api_key)
        self._client: Optional[OpenAI] = None

        if not self.mock_mode and self.api_key:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=60.0,
                max_retries=2,
            )

    def complete_structured(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3000,
    ) -> str:
        """Invokes model expecting structured JSON output."""
        if self.mock_mode or self._client is None:
            raise RuntimeError("Client is in mock mode or API key is not configured.")

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return clean_model_output(content)

    def complete_code(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> str:
        """Invokes model for code synthesis."""
        if self.mock_mode or self._client is None:
            raise RuntimeError("Client is in mock mode or API key is not configured.")

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        return clean_model_output(content)
