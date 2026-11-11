"""NAVER Search API via NAVER API HUB on NAVER Cloud Platform
(https://naverapihub.apigw.ntruss.com, headers X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY;
keys from the NCP console, stored as NAVER_CLIENT_ID / NAVER_CLIENT_KEY).

- reviews(place)  Providers.reviews: blog + cafe search results for "<place> 아기랑"
                  (titles and summary snippets only - no page bodies, no crawling),
                  at most MAX_REVIEWS, only posts that mention the place name

The text is untrusted: the review agent passes it to the LLM as quoted data only.
"""
from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from ..config import load_env

BASE_URL = "https://naverapihub.apigw.ntruss.com"
TIMEOUT_S = 5.0
PER_SOURCE = 10                  # results requested from blog and from cafe each
MAX_REVIEWS = 10
QUERY_SUFFIX = "아기랑"
SOURCES = (("blog", "/search/v1/blog"), ("cafe", "/search/v1/cafearticle"))

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_BRACKET = re.compile(r"\(.*?\)|\[.*?\]")


class NaverClient:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None,
                 http: Optional[httpx.Client] = None):
        if client_id is None or client_secret is None:
            load_env()
            client_id = client_id or os.getenv("NAVER_CLIENT_ID")
            client_secret = client_secret or os.getenv("NAVER_CLIENT_KEY")
        if not client_id or not client_secret:
            raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_KEY are not set")
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT_S)
        self.headers = {"X-NCP-APIGW-API-KEY-ID": client_id, "X-NCP-APIGW-API-KEY": client_secret}

    def _search(self, path: str, query: str) -> list[dict]:
        r = self.http.get(path, params={"query": query, "display": PER_SOURCE, "start": 1, "sort": "sim"},
                          headers=self.headers)
        r.raise_for_status()
        return r.json().get("items") or []

    def reviews(self, place: dict) -> list[dict]:
        """[{title, snippet, link, source, date}] mentioning the place; [] when none do."""
        name = place.get("name", "")
        query = f"{name} {QUERY_SUFFIX}"
        with ThreadPoolExecutor(max_workers=len(SOURCES)) as ex:
            results = list(ex.map(lambda s: (s[0], self._search(s[1], query)), SOURCES))
        keys = name_keys(name)
        out, seen = [], set()
        for source, items in results:
            for it in items:
                title, snippet = clean(it.get("title", "")), clean(it.get("description", ""))
                link = it.get("link", "")
                if not snippet or link in seen or not mentions(f"{title} {snippet}", keys):
                    continue
                seen.add(link)
                out.append({"title": title, "snippet": snippet, "link": link, "source": source,
                            "date": it.get("postdate", "")})
        # interleave blog and cafe so neither crowds the other out
        blog = [r for r in out if r["source"] == "blog"]
        cafe = [r for r in out if r["source"] == "cafe"]
        mixed = [r for pair in zip(blog, cafe) for r in pair] + blog[len(cafe):] + cafe[len(blog):]
        return mixed[:MAX_REVIEWS]


def clean(text: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub("", text or ""))).strip()


def name_keys(name: str) -> list[str]:
    """Forms of the place name to look for: full (spaces removed) and the main part
    without bracketed qualifiers ("국립중앙박물관 어린이박물관" -> also "어린이박물관")."""
    base = _BRACKET.sub(" ", name or "")
    keys = {re.sub(r"\s+", "", base)}
    parts = [p for p in base.split() if len(p) >= 2]
    if len(parts) > 1:
        keys.update(parts)
    return sorted((k for k in keys if len(k) >= 2), key=len, reverse=True)


def mentions(text: str, keys: list[str]) -> bool:
    flat = re.sub(r"\s+", "", text)
    return any(k in flat for k in keys)
