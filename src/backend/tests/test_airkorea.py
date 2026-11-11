"""AirKorea fine-dust forecast client, with a mocked HTTP transport (no network)."""
from datetime import date

import httpx
import pytest

from backend.agents.environment import evaluate_bad_day
from backend.apis.airkorea import (
    BASE_URL, AirKoreaClient, AirKoreaError, forecast_region, nearest_region, parse_grades,
)

TODAY = date(2026, 11, 11)
ALL = "서울 : 보통,경기북부 : 좋음,경기남부 : 보통,영서 : 좋음,영동 : 좋음,광주 : 보통,전남 : 좋음"


def daily_items():
    return [
        {"informCode": "PM10", "informData": "2026-11-12", "dataTime": "2026-11-11 05시 발표", "informGrade": ALL},
        {"informCode": "PM10", "informData": "2026-11-12", "dataTime": "2026-11-11 11시 발표",
         "informGrade": ALL.replace("서울 : 보통", "서울 : 나쁨")},                       # newer issue wins
        {"informCode": "PM25", "informData": "2026-11-12", "dataTime": "2026-11-11 11시 발표", "informGrade": ALL},
    ]


WEEK = [{"presnatnDt": "2026-11-10", "frcstOneDt": "2026-11-13", "frcstOneCn": "서울 : 높음, 강원영서 : 낮음",
         "frcstTwoDt": "2026-11-14", "frcstTwoCn": "서울 : 낮음", "frcstThreeDt": "2026-11-15", "frcstThreeCn": "",
         "frcstFourDt": "2026-11-16", "frcstFourCn": ""}]


def body(items, code="00"):
    return httpx.Response(200, json={"response": {"header": {"resultCode": code}, "body": {"items": items}}})


def client(week_today=None, region_of=None):
    seen = []

    def handler(r):
        seen.append(r)
        if r.url.path.endswith("getMinuDustFrcstDspth"):
            code = r.url.params["InformCode"]
            return body([i for i in daily_items() if i["informCode"] == code])
        # weekly: nothing for today (issued later in the day), yesterday's issue otherwise
        return body(WEEK if r.url.params["searchDate"] == "2026-11-10" or week_today else [])

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return AirKoreaClient(service_key="k", http=http, region_of=region_of, today=lambda: TODAY), seen


def test_forecast_region_from_administrative_region():
    assert forecast_region("경기도", "가평군") == "경기북부"
    assert forecast_region("경기도", "용인시 기흥구") == "경기남부"
    assert forecast_region("강원특별자치도", "강릉시") == "영동"
    assert forecast_region("강원특별자치도", "춘천시") == "영서"
    assert forecast_region("전남광주통합특별시", "동구") == "광주"
    assert forecast_region("전남광주통합특별시", "여수시") == "전남"
    assert forecast_region("서울특별시", "광진구") == "서울"
    assert forecast_region("경상남도", "창원시") == "경남"
    assert forecast_region("어딘가", "") is None
    assert nearest_region(33.25, 126.56) == "제주"


def test_parse_grades_normalizes_gangwon_names():
    assert parse_grades("서울 : 높음, 강원영서 : 낮음") == {"서울": "높음", "영서": "낮음"}


def test_daily_forecast_uses_the_latest_issue():
    a, seen = client(region_of=lambda lat, lng: ("서울특별시", "광진구"))
    assert a.dust(37.5, 127.0, "2026-11-12") == {"pm10_grade": "나쁨", "pm25_grade": "보통", "forecast_source": "daily"}
    q = seen[0].url.params
    assert q["serviceKey"] == "k" and q["returnType"] == "json" and q["searchDate"] == "2026-11-11"


def test_weekly_pm25_after_the_daily_range_and_none_after_that():
    a, _ = client(region_of=lambda lat, lng: ("서울특별시", "광진구"))
    assert a.dust(37.5, 127.0, "2026-11-13") == {"pm10_grade": "예보 없음", "pm25_grade": "높음",
                                                 "forecast_source": "weekly"}
    a, _ = client(region_of=lambda lat, lng: ("강원특별자치도", "춘천시"))
    assert a.dust(37.9, 127.7, "2026-11-13")["pm25_grade"] == "낮음"          # 강원영서 -> 영서
    assert a.dust(37.9, 127.7, "2026-11-20") == {}                             # no forecast


def test_region_lookup_failure_falls_back_and_is_cached():
    calls = []

    def boom(lat, lng):
        calls.append(1)
        raise RuntimeError("kakao down")

    a, _ = client(region_of=boom)
    assert a.region(37.55, 127.0) == "서울" and a.region(37.55, 127.0) == "서울"
    assert len(calls) == 1


def test_bad_day_includes_weekly_high_pm25():
    assert evaluate_bad_day({}, {"pm10_grade": "예보 없음", "pm25_grade": "높음"}) == (True, ["미세먼지"])
    assert evaluate_bad_day({}, {"pm10_grade": "예보 없음", "pm25_grade": "낮음"}) == (False, [])


def test_errors_raise_and_missing_key(monkeypatch):
    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(lambda r: body([], code="30")))
    a = AirKoreaClient(service_key="k", http=http, today=lambda: TODAY)
    with pytest.raises(AirKoreaError):
        a.dust(37.5, 127.0, "2026-11-12")
    monkeypatch.setattr("backend.apis.airkorea.load_env", lambda: None)
    monkeypatch.delenv("PUBLIC_DATA_DECODED_KEY", raising=False)
    with pytest.raises(RuntimeError):
        AirKoreaClient()
