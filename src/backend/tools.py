"""Domain tools: external API access only.

All external access goes through injected `Providers` (the real ones call the
public APIs / Bedrock on the server; tests inject recorded mocks). Every call
runs with a 5 s timeout; a failure or timeout is recorded by source name so
only that piece of information is marked as failed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Optional

API_TIMEOUT_S = 5.0


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


def call_api(fn: Callable, *args) -> Any:
    """Run an API call with the timeout; raises on failure/timeout."""
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args)
    try:
        return fut.result(timeout=API_TIMEOUT_S)
    finally:
        ex.shutdown(wait=False)


def guarded(failed: list[str], source: str, fn: Callable, *args) -> Optional[Any]:
    """`call_api`, but on failure append `source` to `failed` and return None."""
    try:
        return call_api(fn, *args)
    except Exception:
        failed.append(source)
        return None
