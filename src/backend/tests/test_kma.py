"""KMA forecast client, with a mocked HTTP transport and a fixed clock (no network)."""
from datetime import datetime

import httpx
import pytest

from backend.apis.kma import (
    BASE_URL, KMAClient, KMAError, latlng_to_grid, mid_base, nearest_mid_city, short_base,
)

NOW = datetime(2026, 11, 11, 10, 30)           # short-term base 08:00, mid-term issue 06:00


def short_item(day, hour, cat, value):
    return {"fcstDate": day, "fcstTime": f"{hour:02d}00", "category": cat, "fcstValue": str(value)}


SHORT = (
    [short_item("20261112", h, "POP", p) for h, p in ((6, 80), (9, 10), (12, 30), (18, 20), (21, 90))]
    + [short_item("20261112", h, "TMP", t) for h, t in ((6, 2), (9, 8), (12, 15), (18, 10), (21, 4))]
    + [short_item("20261112", 12, "SKY", 3)]
    + [short_item("20261115", h, "POP", 70) for h in (0, 3)] + [short_item("20261115", h, "TMP", 5) for h in (0, 3)]
)
MID_LAND = {"regId": "11B00000", "rnSt5Am": "30", "rnSt5Pm": "60", "rnSt8": "20", "rnSt4Am": "10", "rnSt4Pm": "10"}
MID_TA = {"regId": "11B10101", "taMin5": "3", "taMax5": "12", "taMin8": "-6", "taMax8": "1",
          "taMin4": "4", "taMax4": "13"}


def body(items, code="00"):
    return httpx.Response(200, json={"response": {"header": {"resultCode": code, "resultMsg": "x"},
                                                  "body": {"items": {"item": items}}}})


def client(handler=None):
    seen = []

    def default(r):
        if "getVilageFcst" in r.url.path:
            return body(SHORT)
        if "getMidLandFcst" in r.url.path:
            return body([MID_LAND])
        return body([MID_TA])

    def wrapped(r):
        seen.append(r)
        return (handler or default)(r)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(wrapped))
    return KMAClient(service_key="k", http=http, now=lambda: NOW), seen


def test_grid_conversion_matches_known_points():
    assert latlng_to_grid(37.5665, 126.9780) == (60, 127)        # 서울시청 (KMA reference grid)
    assert latlng_to_grid(35.1796, 129.0756) == (98, 76)         # 부산시청
    assert nearest_mid_city(37.27, 127.11)[0] == "수원"
    assert nearest_mid_city(33.25, 126.56)[0] == "서귀포"


def test_issue_times():
    assert short_base(datetime(2026, 11, 11, 10, 30)) == ("20261111", "0800")
    assert short_base(datetime(2026, 11, 11, 2, 10)) == ("20261110", "2300")     # 02:00 not out yet
    assert mid_base(datetime(2026, 11, 11, 10, 0)) == datetime(2026, 11, 11, 6, 0)
    assert mid_base(datetime(2026, 11, 11, 5, 0)) == datetime(2026, 11, 10, 18, 0)
    assert mid_base(datetime(2026, 11, 11, 19, 0)) == datetime(2026, 11, 11, 18, 0)


def test_short_term_uses_outing_hours():
    k, seen = client()
    w = k.weather(37.5, 127.0, "2026-11-12")
    assert w == {"forecast_source": "short_term", "precip_prob_max": 30, "temp_max": 15.0, "temp_min": 8.0}
    q = seen[0].url.params
    assert (q["nx"], q["ny"], q["base_date"], q["base_time"]) == ("60", "125", "20261111", "0800")
    assert q["serviceKey"] == "k" and q["dataType"] == "JSON"


def test_last_short_term_day_without_daytime_hours_uses_mid_term():
    k, seen = client()
    w = k.weather(37.5, 127.0, "2026-11-15")                     # +4 days: only 00/03 h in short-term
    assert w == {"forecast_source": "mid_term", "precip_prob_max": 10, "temp_max": 13.0, "temp_min": 4.0}


def test_mid_term_morning_afternoon_and_single_values():
    k, seen = client()
    assert k.weather(37.5, 127.0, "2026-11-16") == {           # +5: max of am/pm
        "forecast_source": "mid_term", "precip_prob_max": 60, "temp_max": 12.0, "temp_min": 3.0}
    assert k.weather(37.5, 127.0, "2026-11-19")["temp_min"] == -6.0          # +8: one value per day
    mid = [r for r in seen if "MidFcst" in r.url.path]
    assert {r.url.params["regId"] for r in mid} == {"11B00000", "11B10101"}  # 서울 region / city
    assert {r.url.params["tmFc"] for r in mid} == {"202611110600"}


def test_out_of_range_and_errors_raise():
    k, _ = client()
    with pytest.raises(KMAError):
        k.weather(37.5, 127.0, "2026-11-25")                     # beyond +10 days
    k, _ = client(lambda r: body([], code="03"))
    with pytest.raises(KMAError):
        k.weather(37.5, 127.0, "2026-11-12")
    k, _ = client(lambda r: httpx.Response(200, text="<OpenAPI_ServiceResponse>SERVICE ERROR"))
    with pytest.raises(KMAError):
        k.weather(37.5, 127.0, "2026-11-12")


def test_responses_are_cached():
    k, seen = client()
    for d in ("2026-11-12", "2026-11-12", "2026-11-16", "2026-11-19"):
        k.weather(37.5, 127.0, d)
    paths = [r.url.path.rsplit("/", 1)[1] for r in seen]
    assert paths.count("getVilageFcst") == 1                     # one grid cell, one issue
    assert paths.count("getMidLandFcst") == 1 and paths.count("getMidTa") == 1


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setattr("backend.apis.kma.load_env", lambda: None)
    monkeypatch.delenv("PUBLIC_DATA_DECODED_KEY", raising=False)
    with pytest.raises(RuntimeError):
        KMAClient()
