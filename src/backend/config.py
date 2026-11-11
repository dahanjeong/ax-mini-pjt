"""Backend settings. Secrets and keys are read from the repository-root `.env`
(server side only; real environment variables take precedence)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_BEDROCK_REGION = "us-east-1"
DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"               # judgement + review summary
DEFAULT_BEDROCK_FAST_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"  # extraction, indoor/outdoor
DEFAULT_BEDROCK_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class BedrockSettings:
    region: str = DEFAULT_BEDROCK_REGION
    model_id: str = DEFAULT_BEDROCK_MODEL_ID
    fast_model_id: str = DEFAULT_BEDROCK_FAST_MODEL_ID
    embed_model_id: str = DEFAULT_BEDROCK_EMBED_MODEL_ID
    embed_dimensions: int = 512


def bedrock_settings() -> BedrockSettings:
    load_env()
    return BedrockSettings(
        region=os.getenv("BEDROCK_REGION", DEFAULT_BEDROCK_REGION),
        model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
        fast_model_id=os.getenv("BEDROCK_FAST_MODEL_ID", DEFAULT_BEDROCK_FAST_MODEL_ID),
        embed_model_id=os.getenv("BEDROCK_EMBED_MODEL_ID", DEFAULT_BEDROCK_EMBED_MODEL_ID),
        embed_dimensions=int(os.getenv("BEDROCK_EMBED_DIMENSIONS", "512")),
    )
