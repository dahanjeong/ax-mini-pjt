# 프로젝트 구조

```
mini-pjt/
├── src/
│   ├── frontend/                  # React (Vite) 채팅 UI
│   │   ├── index.html
│   │   ├── package.json
│   │   ├── vite.config.js
│   │   └── src/
│   │       ├── main.jsx           # 진입점
│   │       ├── App.jsx            # 채팅 화면
│   │       └── PlaceCard.jsx      # 추천 결과 카드
│   └── backend/                   # FastAPI 백엔드
│       ├── main.py                # API 서버 진입점
│       ├── agent.py               # Supervisor 그래프 (메시지 분류 · 되묻기 · 재실행 범위 · 일임)
│       ├── intent.py              # 입력 추출 · 의도 판정 · 재실행 범위 결정 (순수 함수)
│       ├── pipeline.py            # 일임 파이프라인 (장소 탐색 → 후보별 환경·후기 → 순위)
│       ├── agents/                # 서브에이전트
│       │   ├── place.py           # 장소 탐색 (반경 · 후보 수집·병합 · 편의시설)
│       │   ├── environment.py     # 환경 (날씨 · 미세먼지 · 나쁜 날 판정)
│       │   ├── review.py          # 후기·적합도 (후기 · LLM 판정·요약 · 실내/야외)
│       │   └── preference.py      # 취향 매칭 (기준 장소 조회 · 프로필 · 임베딩 유사도)
│       ├── apis/                  # 외부 API 클라이언트
│       │   ├── kakao.py           # 카카오 로컬 (출발지 · 장소 · 키워드)
│       │   ├── tourapi.py         # TourAPI (장소 · 편의시설 · 개요 · 키워드)
│       │   └── naver.py           # 네이버 검색 (NAVER API HUB: 블로그 · 카페 후기)
│       ├── tools.py               # 도메인 도구 (외부 API 호출 · 타임아웃 · 실패 기록)
│       ├── bedrock.py             # Bedrock: Claude(추출 · 판정) · Titan 임베딩
│       ├── config.py              # .env 로드 · Bedrock 설정
│       ├── retriever.py           # RAG: 프로필 문장 문서 · 메모리 벡터 저장소 · 코사인 검색
│       ├── constants.py           # 공통 표시 문구·키
│       ├── cards.py               # 결과 카드 생성 · LLM 출력 검증
│       └── tests/                 # pytest 테스트
├── data/                          # 사용한 문서·데이터
│   └── tourapi_categories.json    # TourAPI 분류 코드표 (cat3 → 이름)
├── evaluation/                    # 인-아웃 세트와 자체 평가 결과
│   ├── test_queries.csv           # 인-아웃 세트 (예정)
│   ├── round1_report.md           # 1차 자체 평가 결과 (예정)
│   └── round2_report.md           # 2차 자체 평가 결과 (예정)
├── docs/                          # 개발 문서
├── SERVICE.md                     # 서비스 스펙
├── requirements.txt               # 백엔드 Python 의존성
├── pytest.ini                     # 테스트 설정 (pythonpath = src)
└── README.md
```

## 참고
- 백엔드 모듈은 `src`를 기준으로 import한다 (`from backend.agent import ...`). 서버 실행 시 `--app-dir src`를 준다.
- API 키는 저장소 루트의 `.env`에만 두며 git에 올리지 않는다.
