"""Wire the real external clients into `tools.Providers` and the supervisor `Deps`."""
from __future__ import annotations

from typing import Optional

from ..agent import Deps
from .airkorea import AirKoreaClient
from .kakao import KakaoClient
from .kma import KMAClient
from .naver import NaverClient
from .tourapi import TourClient
from .bedrock import BedrockEmbedder, BedrockLLM
from ..tools import Providers


def build_providers(*, tour: Optional[TourClient] = None, kakao: Optional[KakaoClient] = None,
                    naver: Optional[NaverClient] = None, llm: Optional[BedrockLLM] = None,
                    embedder: Optional[BedrockEmbedder] = None, kma: Optional[KMAClient] = None,
                    airkorea: Optional[AirKoreaClient] = None) -> Providers:
    tour, kakao = tour or TourClient(), kakao or KakaoClient()
    naver, llm, embedder = naver or NaverClient(), llm or BedrockLLM(), embedder or BedrockEmbedder()
    kma = kma or KMAClient()
    airkorea = airkorea or AirKoreaClient(region_of=kakao.region)

    def keyword_search(query, lat=None, lng=None, radius_km=None):
        # TourAPI first: its places carry facility data and an overview
        return tour.keyword_search(query, lat, lng, radius_km) + kakao.keyword_search(query, lat, lng, radius_km)

    return Providers(
        tour_search=tour.location_search,
        kakao_search=kakao.category_search,
        facilities=tour.facilities,
        reviews=naver.reviews,
        weather=kma.weather,
        dust=airkorea.dust,
        llm_judge=llm.judge,
        llm_indoor_outdoor=llm.classify_indoor_outdoor,
        keyword_search=keyword_search,
        embed=embedder.embed,
        drive_minutes=kakao.drive_minutes,
    )


def build_deps(*, kakao: Optional[KakaoClient] = None, llm: Optional[BedrockLLM] = None) -> Deps:
    return Deps(geocode=(kakao or KakaoClient()).geocode, extractor=(llm or BedrockLLM()).extract)
