"""AWS Bedrock access: Claude for the LLM steps, Titan for embeddings.

- Claude: the official Anthropic SDK's Bedrock client (`AnthropicBedrock`, the
  bedrock-runtime path, one client per region). Each task has its own chain of
  (region, model) entries starting on a different region/model (config.DEFAULT_*_MODELS):
  the judge (age suitability + review summary) uses Sonnet only, extraction and
  indoor/outdoor use Haiku. When an entry answers 429 (e.g. the shared account's daily
  token quota is used up), the next entry is tried. The SDK is pinned below 2.0.0 because Sonnet 4.6 on
  Bedrock does not accept the API version that 2.x sends.
- Every LLM step forces one tool call whose input schema is the answer shape, so
  the reply is structured JSON; the answer is still validated (prompts/: parse_llm_judgement,
  normalize_extraction, parse_setting). The prompts themselves live in prompts/.
- Throttling: at most MAX_CONCURRENT requests per model run at once (the rest
  queue), and the SDK retries 429 / 5xx with exponential backoff (LLM_MAX_RETRIES).
- Titan Text Embeddings v2 takes one text per call: calls run in parallel and
  repeated sentences are served from an in-process cache; boto3 retries throttling
  in adaptive mode.

    llm = BedrockLLM()
    Deps(..., extractor=llm.extract)
    Providers(..., llm_judge=llm.judge, llm_indoor_outdoor=llm.classify_indoor_outdoor,
              embed=BedrockEmbedder().embed)
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from ..core.config import BedrockSettings, bedrock_settings
from ..prompts.extract import EXTRACT_SYSTEM, EXTRACT_TOOL, build_extract_prompt, normalize_extraction  # noqa: F401
from ..prompts.judge import JUDGE_SYSTEM, JUDGE_TOOL, build_judge_message, parse_llm_judgement
from ..prompts.setting import SETTING_SYSTEM, SETTING_TOOL, build_setting_prompt, parse_setting

LLM_TIMEOUT_S = 15.0         # one HTTP request
LLM_MAX_RETRIES = 1          # the SDK retries 429 / 5xx / connection errors once (exponential
                             # backoff, honours retry-after); after that the next model is tried
QUEUE_TIMEOUT_S = 15.0       # longest wait for a free concurrency slot
# simultaneous requests per model (Bedrock quotas are per model)
MAX_CONCURRENT = {"judge": 6, "extract": 8, "classify": 8}
MAX_TOKENS = 1024
# Deterministic judgements. SDK 1.x dropped the `temperature` argument, so it is sent in the
# request body; the API version the pinned SDK sends to Bedrock accepts it for the Sonnet 4.6 /
# 4.5 and Haiku 4.5 models used here. API version 2026-10-21 (SDK 2.x) rejects sampling
# parameters: remove this when upgrading.
TEMPERATURE = 0.0
EMBED_WORKERS = 8
EMBED_CACHE_MAX = 5000


class LLMRefusal(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    """Every model in the task's chain answered 429."""


def _rate_limited(e: Exception) -> bool:
    return getattr(e, "status_code", None) == 429


class LLMBusy(TimeoutError):
    """No concurrency slot became free in time (treated like any other failure)."""


_SLOTS: dict[str, threading.BoundedSemaphore] = {}
_SLOTS_LOCK = threading.Lock()


def _slot(model: str, limit: int) -> threading.BoundedSemaphore:
    """One semaphore per `region/model`, shared by every BedrockLLM in the process."""
    with _SLOTS_LOCK:
        if model not in _SLOTS:
            _SLOTS[model] = threading.BoundedSemaphore(limit)
        return _SLOTS[model]


# ---------------------------------------------------------------- Claude

class BedrockLLM:
    def __init__(self, settings: Optional[BedrockSettings] = None, client: Any = None):
        self.settings = settings or bedrock_settings()
        self.client = client                  # tests inject one fake client for every region
        self._clients: dict[str, Any] = {}
        self._clients_lock = threading.Lock()

    def _client_for(self, region: str) -> Any:
        if self.client is not None:
            return self.client
        with self._clients_lock:
            if region not in self._clients:
                from anthropic import AnthropicBedrock  # imported lazily: tests inject a fake client
                self._clients[region] = AnthropicBedrock(aws_region=region, timeout=LLM_TIMEOUT_S,
                                                         max_retries=LLM_MAX_RETRIES)
            return self._clients[region]

    def _chain(self, task: str) -> tuple[str, ...]:
        return {"judge": self.settings.judge_models, "extract": self.settings.extract_models,
                "classify": self.settings.classify_models}[task]

    def _tool_call(self, *, task: str, system: str, user: str, tool: dict, max_tokens: int = MAX_TOKENS) -> dict:
        last: Optional[Exception] = None
        for region, model in self._chain(task):
            try:
                return self._on_model(region=region, model=model, limit=MAX_CONCURRENT[task],
                                      system=system, user=user, tool=tool, max_tokens=max_tokens)
            except Exception as e:
                if not _rate_limited(e):
                    raise
                last = e                                      # quota / throttling: next model
        raise LLMUnavailable(f"every {task} model is rate limited: {last}")

    def _on_model(self, *, region: str, model: str, limit: int, system: str, user: str, tool: dict,
                  max_tokens: int = MAX_TOKENS) -> dict:
        slot = _slot(f"{region}/{model}", limit)
        if not slot.acquire(timeout=QUEUE_TIMEOUT_S):
            raise LLMBusy(f"no free slot for {model} within {QUEUE_TIMEOUT_S}s")
        try:
            return self._call(client=self._client_for(region), model=model, system=system, user=user, tool=tool,
                              max_tokens=max_tokens)
        finally:
            slot.release()

    def _call(self, *, client: Any, model: str, system: str, user: str, tool: dict,
              max_tokens: int = MAX_TOKENS) -> dict:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user}],
            extra_body={"temperature": TEMPERATURE},          # SDK 1.x has no `temperature` argument
        )
        if response.stop_reason == "max_tokens":
            raise ValueError(f"{tool['name']} answer was cut off at max_tokens={max_tokens}")
        if response.stop_reason == "refusal":
            raise LLMRefusal(getattr(response, "stop_details", None))
        for block in response.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return dict(block.input)
        raise ValueError(f"no {tool['name']} call in the response (stop_reason={response.stop_reason})")

    # general structured call on the judge (Sonnet) chain, e.g. the evaluation grader
    def call_tool(self, *, system: str, user: str, tool: dict, max_tokens: int = MAX_TOKENS) -> dict:
        return self._tool_call(task="judge", system=system, user=user, tool=tool, max_tokens=max_tokens)

    # Deps.extractor(message, awaiting) -> partial dict
    def extract(self, message: str, awaiting: Optional[str]) -> dict:
        raw = self._tool_call(task="extract", system=EXTRACT_SYSTEM, user=build_extract_prompt(message, awaiting),
                              tool=EXTRACT_TOOL)
        return normalize_extraction(raw)

    # Providers.llm_judge(place, age_months, reviews) -> {age_suitability, summary, facility_mentions}
    def judge(self, place: dict, age_months: int, reviews: list[dict]) -> dict:
        raw = self._tool_call(task="judge", system=JUDGE_SYSTEM, user=build_judge_message(place, age_months, reviews),
                              tool=JUDGE_TOOL)
        return parse_llm_judgement(raw)

    # Providers.llm_indoor_outdoor(place, reviews) -> "indoor" | "outdoor"
    def classify_indoor_outdoor(self, place: dict, reviews: list[dict]) -> str:
        raw = self._tool_call(task="classify", system=SETTING_SYSTEM, user=build_setting_prompt(place, reviews),
                              tool=SETTING_TOOL)
        return parse_setting(raw)


# ---------------------------------------------------------------- Titan embeddings

class BedrockEmbedder:
    def __init__(self, settings: Optional[BedrockSettings] = None, client: Any = None):
        self.settings = settings or bedrock_settings()
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client(
                "bedrock-runtime", region_name=self.settings.region,
                # adaptive: retries throttling with backoff and slows the client down
                config=Config(read_timeout=LLM_TIMEOUT_S, connect_timeout=5,
                              retries={"max_attempts": 4, "mode": "adaptive"}),
            )
        self.client = client
        self._cache: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _embed_one(self, text: str) -> list[float]:
        with self._lock:
            hit = self._cache.get(text)
        if hit is not None:
            return hit
        resp = self.client.invoke_model(
            modelId=self.settings.embed_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": self.settings.embed_dimensions,
                             "normalize": True}),
        )
        vec = json.loads(resp["body"].read())["embedding"]
        with self._lock:
            if len(self._cache) >= EMBED_CACHE_MAX:
                self._cache.clear()
            self._cache[text] = vec
        return vec

    # Providers.embed(texts) -> one vector per text, same order
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with ThreadPoolExecutor(max_workers=min(EMBED_WORKERS, len(texts))) as ex:
            return list(ex.map(self._embed_one, texts))
