"""Bedrock adapters, with fake clients (no AWS calls)."""
import io
import json
from types import SimpleNamespace

import pytest

from backend import tools
from backend.integrations.bedrock import (
    EXTRACT_TOOL, JUDGE_TOOL, SETTING_TOOL, BedrockEmbedder, BedrockLLM, LLMRefusal,
    normalize_extraction,
)
from backend.core.config import (
    DEFAULT_BEDROCK_REGION, DEFAULT_CLASSIFY_MODELS, DEFAULT_EXTRACT_MODELS, DEFAULT_JUDGE_MODELS,
    BedrockSettings, bedrock_settings,
)

SETTINGS = BedrockSettings()


class FakeMessages:
    def __init__(self, tool_input, stop_reason="tool_use", tool_name=None):
        self.tool_input, self.stop_reason, self.tool_name = tool_input, stop_reason, tool_name
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        name = self.tool_name or kw["tools"][0]["name"]
        block = SimpleNamespace(type="tool_use", name=name, input=self.tool_input)
        return SimpleNamespace(stop_reason=self.stop_reason, stop_details=None,
                               content=[] if self.stop_reason == "refusal" else [block])


def llm(tool_input, **kw):
    msgs = FakeMessages(tool_input, **kw)
    return BedrockLLM(SETTINGS, client=SimpleNamespace(messages=msgs)), msgs


def test_default_model_chains(monkeypatch):
    monkeypatch.setattr("backend.core.config.load_env", lambda: None)     # ignore the local .env
    for k in ("BEDROCK_REGION", "BEDROCK_JUDGE_MODELS", "BEDROCK_EXTRACT_MODELS", "BEDROCK_CLASSIFY_MODELS"):
        monkeypatch.delenv(k, raising=False)
    s = bedrock_settings()
    assert s.region == DEFAULT_BEDROCK_REGION == "us-east-1"            # embeddings
    assert s.judge_models == DEFAULT_JUDGE_MODELS
    assert s.judge_models[0] == ("us-west-2", "us.anthropic.claude-sonnet-4-6")
    assert all("sonnet" in m for _, m in s.judge_models)                # the judge uses Sonnet only
    assert all("haiku" in m for _, m in s.extract_models + s.classify_models)
    # every task starts on a different region/model
    assert len({s.judge_models[0], s.extract_models[0], s.classify_models[0]}) == 3
    assert {r for r, _ in s.judge_models} == {"us-east-1", "us-west-2", "ap-northeast-2"}


def test_model_chain_from_env(monkeypatch):
    monkeypatch.setattr("backend.core.config.load_env", lambda: None)
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_JUDGE_MODELS", " us-west-2/us.anthropic.claude-sonnet-4-6 , global.x-v1:0 ,")
    assert bedrock_settings().judge_models == (("us-west-2", "us.anthropic.claude-sonnet-4-6"),
                                               ("us-east-1", "global.x-v1:0"))


def test_extract_forces_the_tool_and_normalizes():
    model, msgs = llm({"age_months": 18, "departure_query": " 강남역 ", "date_text": "이번 토요일",
                       "travels_during_nap": None, "preference_text": "조용한 곳",
                       "preference_keywords": ["조용한 공원", "", 3], "reference_place": None})
    out = model.extract("18개월 아기랑 이번 토요일 강남역에서, 조용한 곳", "date")
    assert out == {"age_months": 18, "departure_query": "강남역", "date_text": "이번 토요일",
                   "preference_text": "조용한 곳", "preference_keywords": ["조용한 공원"]}
    call = msgs.calls[0]
    assert call["model"] == DEFAULT_EXTRACT_MODELS[0][1]
    assert call["tools"] == [EXTRACT_TOOL]
    assert call["tool_choice"] == {"type": "tool", "name": "record_outing_request"}
    assert "<message>" in call["messages"][0]["content"] and "date" in call["messages"][0]["content"]
    assert call["extra_body"] == {"temperature": 0.0}     # deterministic answers (pinned SDK 1.x)
    assert "temperature" not in call                      # SDK 1.x rejects it as an argument


def test_normalize_extraction_drops_bad_types():
    assert normalize_extraction({"age_months": True, "departure_query": 3, "travels_during_nap": "yes"}) == {}
    assert normalize_extraction("nope") == {}
    assert normalize_extraction({"travels_during_nap": False}) == {"travels_during_nap": False}


def test_judge_output_goes_through_the_fixed_schema_validation():
    model, msgs = llm({"age_suitability": "적합", "summary": ["a", "b", "c"],
                       "facility_mentions": {"nursing_room": "있음", "parking": "언급 없음"}})
    out = model.judge({"name": "공룡관", "types": ["tourapi:14"]}, 30, [{"title": "t", "snippet": "s"}])
    assert out == {"age_suitability": "적합", "summary": ["a", "b", "c"],
                   "facility_mentions": {"nursing_room": "있음"}}
    call = msgs.calls[0]
    assert call["model"] == DEFAULT_JUDGE_MODELS[0][1]
    assert call["tools"] == [JUDGE_TOOL] and "<reviews>" in call["messages"][0]["content"]

    model, _ = llm({"age_suitability": "최고", "summary": [], "facility_mentions": {}})
    assert model.judge({"name": "x"}, 30, [])["age_suitability"] == "보통"  # invalid -> safe default


def test_classify_indoor_outdoor():
    model, msgs = llm({"setting": "indoor"})
    assert model.classify_indoor_outdoor({"name": "x"}, []) == "indoor"
    assert msgs.calls[0]["tools"] == [SETTING_TOOL]
    assert msgs.calls[0]["model"] == DEFAULT_CLASSIFY_MODELS[0][1]
    model, _ = llm({"setting": "garage"})
    with pytest.raises(ValueError):
        model.classify_indoor_outdoor({"name": "x"}, [])


def test_refusal_and_missing_tool_call_raise():
    model, _ = llm({}, stop_reason="refusal")
    with pytest.raises(LLMRefusal):
        model.extract("hi", None)
    model, _ = llm({}, tool_name="something_else")
    with pytest.raises(ValueError):
        model.extract("hi", None)


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def invoke_model(self, **kw):
        body = json.loads(kw["body"])
        self.calls.append((kw["modelId"], body))
        vec = [float(len(body["inputText"])), 1.0]
        return {"body": io.BytesIO(json.dumps({"embedding": vec}).encode())}


def test_titan_embedder_keeps_order_and_caches():
    rt = FakeRuntime()
    emb = BedrockEmbedder(SETTINGS, client=rt)
    out = emb.embed(["a", "bbb", "a", "cc"])
    assert out == [[1.0, 1.0], [3.0, 1.0], [1.0, 1.0], [2.0, 1.0]]
    assert {c[0] for c in rt.calls} == {"amazon.titan-embed-text-v2:0"}
    assert rt.calls[0][1]["dimensions"] == 512 and rt.calls[0][1]["normalize"] is True
    n = len(rt.calls)
    emb.embed(["a", "bbb"])
    assert len(rt.calls) == n                      # served from the cache
    assert emb.embed([]) == []


def test_llm_and_embedding_get_the_longer_timeout(monkeypatch):
    seen = {}

    def fake_call_api(fn, *args, timeout=None):
        seen[fn.__name__] = timeout
        return fn(*args)

    monkeypatch.setattr(tools, "call_api", fake_call_api)

    def llm_fn():
        return 1

    def embedding_fn():
        return 1

    def weather_fn():
        return 1

    tools.guarded([], "llm", llm_fn)
    tools.guarded([], "embedding", embedding_fn)
    tools.guarded([], "kma", weather_fn)
    assert seen == {"llm_fn": tools.SLOW_TIMEOUT_S, "embedding_fn": tools.SLOW_TIMEOUT_S, "weather_fn": None}


# ---------------------------------------------------------------- throttling

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from backend.integrations import bedrock


class SlowMessages:
    """Records how many requests run at the same time."""

    def __init__(self, delay=0.1):
        self.delay, self.active, self.peak = delay, 0, 0
        self.lock = threading.Lock()

    def create(self, **kw):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        block = SimpleNamespace(type="tool_use", name=kw["tools"][0]["name"],
                                input={"age_suitability": "적합", "summary": [], "facility_mentions": {}})
        return SimpleNamespace(stop_reason="tool_use", content=[block])


@pytest.fixture
def fresh_slots(monkeypatch):
    monkeypatch.setattr(bedrock, "_SLOTS", {})


def test_concurrent_requests_per_model_are_limited(fresh_slots, monkeypatch):
    monkeypatch.setattr(bedrock, "MAX_CONCURRENT", {"judge": 3, "extract": 5, "classify": 5})
    msgs = SlowMessages()
    model = BedrockLLM(SETTINGS, client=SimpleNamespace(messages=msgs))
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(lambda i: model.judge({"name": f"p{i}"}, 30, []), range(12)))
    assert msgs.peak == 3


def test_waiting_too_long_for_a_slot_fails(fresh_slots, monkeypatch):
    monkeypatch.setattr(bedrock, "MAX_CONCURRENT", {"judge": 1, "extract": 1, "classify": 1})
    monkeypatch.setattr(bedrock, "QUEUE_TIMEOUT_S", 0.05)
    model = BedrockLLM(SETTINGS, client=SimpleNamespace(messages=SlowMessages(delay=0.5)))
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(model.judge, {"name": "a"}, 30, []), ex.submit(model.judge, {"name": "b"}, 30, [])]
        outcomes = []
        for f in futs:
            try:
                f.result()
                outcomes.append("ok")
            except bedrock.LLMBusy:
                outcomes.append("busy")
    assert sorted(outcomes) == ["busy", "ok"]


def test_real_clients_retry_throttling():
    model = BedrockLLM(SETTINGS)              # builds AnthropicBedrock clients; no request is sent
    west, seoul = model._client_for("us-west-2"), model._client_for("ap-northeast-2")
    assert west is model._client_for("us-west-2") and west is not seoul      # one client per region
    assert west.max_retries == bedrock.LLM_MAX_RETRIES == 1
    emb = BedrockEmbedder(SETTINGS)           # builds a boto3 client; no request is sent
    retries = emb.client.meta.config.retries
    assert retries["mode"] == "adaptive" and retries["total_max_attempts"] == 5  # 1 try + 4 retries



# ---------------------------------------------------------------- fallback on 429

class Throttled(Exception):
    status_code = 429


class ChainMessages:
    """Answers 429 for the models in `limited`, a judgement for the others."""

    def __init__(self, limited, error=Throttled):
        self.limited, self.error, self.models = set(limited), error, []

    def create(self, **kw):
        self.models.append(kw["model"])
        if kw["model"] in self.limited:
            raise self.error("Too many tokens per day")
        block = SimpleNamespace(type="tool_use", name=kw["tools"][0]["name"],
                                input={"age_suitability": "적합", "summary": [], "facility_mentions": {}})
        return SimpleNamespace(stop_reason="tool_use", content=[block])


def test_rate_limited_model_falls_back_to_the_next_in_the_chain(fresh_slots):
    msgs = ChainMessages(limited=[DEFAULT_JUDGE_MODELS[0][1]])
    model = BedrockLLM(SETTINGS, client=SimpleNamespace(messages=msgs))
    assert model.judge({"name": "x"}, 30, [])["age_suitability"] == "적합"
    assert msgs.models == [m for _, m in DEFAULT_JUDGE_MODELS[:2]]


def test_every_model_rate_limited_raises(fresh_slots):
    msgs = ChainMessages(limited=[m for _, m in DEFAULT_JUDGE_MODELS])
    model = BedrockLLM(SETTINGS, client=SimpleNamespace(messages=msgs))
    with pytest.raises(bedrock.LLMUnavailable):
        model.judge({"name": "x"}, 30, [])
    assert msgs.models == [m for _, m in DEFAULT_JUDGE_MODELS]          # every entry tried, Sonnet only


def test_other_errors_do_not_fall_back(fresh_slots):
    msgs = ChainMessages(limited=[DEFAULT_JUDGE_MODELS[0][1]], error=RuntimeError)
    model = BedrockLLM(SETTINGS, client=SimpleNamespace(messages=msgs))
    with pytest.raises(RuntimeError):
        model.judge({"name": "x"}, 30, [])
    assert msgs.models == [DEFAULT_JUDGE_MODELS[0][1]]


def test_answer_cut_off_at_max_tokens_is_an_error():
    model, msgs = llm({"age_suitability": "적합"}, stop_reason="max_tokens")
    with pytest.raises(ValueError):
        model.judge({"name": "x"}, 30, [])
    model, msgs = llm({"traits": [], "forbidden": []})
    model.call_tool(system="s", user="u", tool={"name": "record_grades", "input_schema": {}}, max_tokens=4096)
    assert msgs.calls[-1]["max_tokens"] == 4096
