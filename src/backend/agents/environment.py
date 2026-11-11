"""Environment: weather and fine-dust forecast for a place, and bad-day judgement."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..constants import FAIL, NO_DUST
from ..tools import Providers, guarded

BAD_GRADES = {"나쁨", "매우나쁨", "매우 나쁨"}
RAIN_PROB = 60
HEAT_C = 33
COLD_C = -5


def evaluate_bad_day(w: dict, d: dict) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if isinstance(w.get("precip_prob_max"), (int, float)) and w["precip_prob_max"] >= RAIN_PROB:
        warnings.append("강수")
    if d.get("pm10_grade") in BAD_GRADES or d.get("pm25_grade") in BAD_GRADES:
        warnings.append("미세먼지")
    if isinstance(w.get("temp_max"), (int, float)) and w["temp_max"] >= HEAT_C:
        warnings.append("폭염")
    if isinstance(w.get("temp_min"), (int, float)) and w["temp_min"] <= COLD_C:
        warnings.append("한파")
    return bool(warnings), warnings


def assess_environment(prov: Providers, p: dict, date_str: str) -> dict:
    """Weather + dust for the place on `date_str` (fetched in parallel)."""
    wf: list[str] = []
    df: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_w = ex.submit(guarded, wf, "kma", prov.weather, p["lat"], p["lng"], date_str)
        f_d = ex.submit(guarded, df, "airkorea", prov.dust, p["lat"], p["lng"], date_str)
        weather, dust = f_w.result(), f_d.result()

    if dust is None:
        dust_out = {"status": FAIL}
    elif not dust:
        dust_out = {"status": NO_DUST}
    else:
        dust_out = dict(dust)
    bad, warns = evaluate_bad_day(weather or {}, dust or {})
    return {
        "weather": {"status": FAIL} if weather is None else dict(weather),
        "dust": dust_out,
        "is_bad_day": bad,
        "bad_day_warnings": warns,
        "failed_sources": wf + df,
    }
