"""Domain tools: external API access only.

All external access goes through injected `Providers` (the real ones call the
public APIs / Bedrock on the server; tests inject recorded mocks). Every call
runs with a timeout (5 s for public/search APIs, 20 s for Bedrock LLM and
embedding calls); a failure or timeout is recorded by source name so
only that piece of information is marked as failed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Optional

API_TIMEOUT_S = 5.0          # public data / search APIs
SLOW_TIMEOUT_S = 20.0        # Bedrock LLM and embedding calls (includes queueing + retries)
SLOW_SOURCES = {"llm", "embedding"}


@dataclass
class Providers:
    # tour_search/kakao_search(lat, lng, radius_km) -> raw places (region-code based collection)
    tour_search: Callable[[float, float, float], list[dict]]
    kakao_search: Callable[[float, float, float], list[dict]]
    facilities: Callable[[dict], dict]            # public-data facilities: {key: 있음/없음/정보 없음}
    reviews: Callable[[dict], list[dict]]         # NAVER blog/cafe snippets (<=10)
    weather: Callable[[float, float, str], dict]  # {forecast_source, precip_prob_max, temp_max, temp_min}
    dust: Callable[[float, float, str], dict]     # {pm10_grade, pm25_grade} or {} when no forecast
    llm_judge: Callable[[dict, int, list], dict]  # {age_suitability, summary[3], facility_mentions{}}
    llm_indoor_outdoor: Callable[[dict, list], str]
    # optional (preference matching); None -> recommend without preference matching
    # keyword_search(query, lat, lng, radius_km) -> raw places like tour/kakao (+ "source");
    #   lat/lng/radius None = nationwide (reference-place lookup)
    keyword_search: Optional[Callable[[str, Optional[float], Optional[float], Optional[float]], list[dict]]] = None
    # embed(texts) -> one vector per text (Bedrock embeddings)
    embed: Optional[Callable[[list[str]], list[list[float]]]] = None


def call_api(fn: Callable, *args, timeout: Optional[float] = None) -> Any:
    """Run an API call with the timeout (default API_TIMEOUT_S); raises on failure/timeout."""
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=API_TIMEOUT_S if timeout is None else timeout)
    finally:
        ex.shutdown(wait=False)


def guarded(failed: list[str], source: str, fn: Callable, *args) -> Optional[Any]:
    """`call_api`, but on failure append `source` to `failed` and return None.
    LLM / embedding sources get the longer SLOW_TIMEOUT_S."""
    try:
        return call_api(fn, *args, timeout=SLOW_TIMEOUT_S if source in SLOW_SOURCES else None)
    except Exception:
        failed.append(source)
        return None
