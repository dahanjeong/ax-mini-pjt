"""Backend settings. Secrets and keys are read from the repository-root `.env`
(server side only; real environment variables take precedence)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]          # repository root (src/backend/core/config.py)

DEFAULT_BEDROCK_REGION = "us-east-1"
# One chain of (region, model) per task. Bedrock quotas are per region, per model and
# per inference profile (global. / us.), and the account is shared, so each task starts
# on a different region/model and falls through to the next entry on a 429.
# The judge uses Sonnet only (4.6 before 4.5); extraction and indoor/outdoor use Haiku.
USE1, USW2, APNE2 = "us-east-1", "us-west-2", "ap-northeast-2"
SONNET_46, SONNET_45 = "anthropic.claude-sonnet-4-6", "anthropic.claude-sonnet-4-5-20250929-v1:0"
HAIKU_45 = "anthropic.claude-haiku-4-5-20251001-v1:0"
DEFAULT_JUDGE_MODELS = (
    (USW2, f"us.{SONNET_46}"), (APNE2, f"global.{SONNET_46}"), (USE1, f"us.{SONNET_46}"),
    (USW2, f"global.{SONNET_46}"),
    (USW2, f"us.{SONNET_45}"), (APNE2, f"global.{SONNET_45}"), (USE1, f"global.{SONNET_45}"),
    (USW2, f"global.{SONNET_45}"),
    (USE1, f"global.{SONNET_46}"), (USE1, f"us.{SONNET_45}"),
)
DEFAULT_EXTRACT_MODELS = ((APNE2, f"global.{HAIKU_45}"), (USE1, f"global.{HAIKU_45}"), (USW2, f"global.{HAIKU_45}"))
DEFAULT_CLASSIFY_MODELS = ((USW2, f"us.{HAIKU_45}"), (USE1, f"us.{HAIKU_45}"), (USW2, f"global.{HAIKU_45}"))
DEFAULT_BEDROCK_EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"


def load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class BedrockSettings:
    region: str = DEFAULT_BEDROCK_REGION
    judge_models: tuple[tuple[str, str], ...] = DEFAULT_JUDGE_MODELS       # (region, model id)
    extract_models: tuple[tuple[str, str], ...] = DEFAULT_EXTRACT_MODELS
    classify_models: tuple[tuple[str, str], ...] = DEFAULT_CLASSIFY_MODELS
    embed_model_id: str = DEFAULT_BEDROCK_EMBED_MODEL_ID
    embed_dimensions: int = 512


def _models(env: str, default: tuple) -> tuple:
    """`region/model,region/model` from the environment (model ids contain ':'), else the default.
    An entry without a region uses BEDROCK_REGION."""
    raw = os.getenv(env, "")
    chain = []
    for item in (x.strip() for x in raw.split(",") if x.strip()):
        region, _, model = item.rpartition("/")
        chain.append((region or os.getenv("BEDROCK_REGION", DEFAULT_BEDROCK_REGION), model))
    return tuple(chain) or default


def bedrock_settings() -> BedrockSettings:
    load_env()
    return BedrockSettings(
        region=os.getenv("BEDROCK_REGION", DEFAULT_BEDROCK_REGION),
        judge_models=_models("BEDROCK_JUDGE_MODELS", DEFAULT_JUDGE_MODELS),
        extract_models=_models("BEDROCK_EXTRACT_MODELS", DEFAULT_EXTRACT_MODELS),
        classify_models=_models("BEDROCK_CLASSIFY_MODELS", DEFAULT_CLASSIFY_MODELS),
        embed_model_id=os.getenv("BEDROCK_EMBED_MODEL_ID", DEFAULT_BEDROCK_EMBED_MODEL_ID),
        embed_dimensions=int(os.getenv("BEDROCK_EMBED_DIMENSIONS", "512")),
    )
