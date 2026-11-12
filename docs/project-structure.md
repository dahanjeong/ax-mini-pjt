# 프로젝트 구조

```
mini-pjt/
├── src/
│   ├── frontend/                  # React (Vite) 채팅 UI
│   │   ├── index.html
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── tsconfig.json          # strict, 타입만 지울 수 있는 문법 (node가 테스트를 바로 실행)
│   │   └── src/
│   │       ├── main.tsx           # 진입점
│   │       ├── App.tsx            # 화면 조립 (feature 조합 · 입력 상태)
│   │       ├── components/        # 재사용 컴포넌트 (docs/frontend-components.md)
│   │       │   ├── base/          # 스타일 없는 Base: 동작 · 시맨틱 · 접근성만
│   │       │   └── ui/            # Base에 디자인 토큰 스타일을 입힌 컴포넌트 (+ 컴포넌트별 .css)
│   │       ├── features/          # 도메인 화면 조각 (ui 조합)
│   │       │   ├── chat/          # 상단바 · 소개 · 예시 질문 · 대화 턴 · useChat(세션·전송)
│   │       │   └── place/         # 추천 결과 카드 (이동시간 · 편의시설 · 취향 일치 · 후기 출처)
│   │       ├── hooks/             # 화면 동작 훅 (자동 스크롤 · 응답 후 입력창 포커스)
│   │       ├── api.ts             # 백엔드 호출 (/chat, /health — 로컬 백엔드만)
│   │       ├── types.ts           # 백엔드 응답 타입 (api/schemas.py · supervisor/cards.py와 같은 형태)
│   │       ├── format.ts          # 표시용 함수 (날씨·대기·편의시설·응답 → 말풍선)
│   │       ├── format.test.ts     # format.ts 테스트 (npm test)
│   │       ├── tokens.css · base.css  # 디자인 토큰 · 리셋
│   │       └── styles.css         # 앱 셸 레이아웃만
│   └── backend/             # FastAPI 백엔드
│       ├── main.py              # FastAPI 진입점
│       ├── api/                 # 우리가 제공하는 API
│       │   ├── chat.py          # POST /chat: 세션 · 한 턴 실행 · 결과 카드 · 오류 처리
│       │   └── schemas.py       # 요청 / 응답 형식
│       ├── agent.py             # Supervisor 그래프 (메시지 분류 · 되묻기 · 재실행 범위 · 일임)
│       ├── tools.py             # 도메인 도구 계약 (Providers) · 타임아웃 · 실패 기록
│       ├── retriever.py         # RAG: 장소 프로필 문장 · 메모리 벡터 저장소 · 코사인 검색
│       ├── supervisor/          # agent.py가 쓰는 부품
│       │   ├── intent.py        # 입력 추출(규칙) · 의도 판정 · 재실행 범위 결정 (순수 함수)
│       │   ├── pipeline.py      # 일임 파이프라인 (장소 탐색 → 후보별 환경·후기 → 취향 매칭 → 순위 · 다양성)
│       │   └── cards.py         # 결과 카드 생성 (고정 필드)
│       ├── agents/              # 서브에이전트
│       │   ├── place.py         # 장소 탐색 서브그래프 (반경 · 후보 수집 · 편의시설 조회)
│       │   ├── candidates.py    # 후보 처리 규칙 (정규화 · 병합 · 같은 시설 묶기 · 나들이 등급 · 후보 선정)
│       │   ├── environment.py   # 환경 서브그래프 (날씨 · 미세먼지 · 나쁜 날 판정)
│       │   ├── review.py        # 후기·적합도 서브그래프 (후기 · LLM 판정·요약 · 실내/야외)
│       │   └── preference.py    # 취향 매칭 서브그래프 (기준 장소 조회 · 프로필 · 임베딩 유사도)
│       ├── prompts/             # LLM에게 무엇을 물을지 (프롬프트 · 답 스키마 · 답 검증)
│       │   ├── judge.py         # 월령 적합도 기준 · 후기 요약 규칙 · 판정 답 검증
│       │   ├── extract.py       # 입력 추출
│       │   ├── setting.py       # 실내/야외 분류
│       │   └── common.py        # 장소 정보 블록
│       ├── integrations/        # 연동 서비스 (어떻게 부를지)
│       │   ├── kakao.py         # 카카오 로컬: 출발지 좌표 · 반경 내 장소 · 키워드 · 좌표→행정구역
│       │   ├── tourapi.py       # TourAPI: 반경 내 장소 · 편의시설(소개·무장애) · 개요 · 키워드
│       │   ├── naver.py         # 네이버 검색 (NAVER API HUB): 블로그·카페 후기 요약문
│       │   ├── kma.py           # 기상청 단기·중기예보
│       │   ├── airkorea.py      # 에어코리아 미세먼지 예보
│       │   ├── bedrock.py       # AWS Bedrock: Claude 호출(지역·모델 체인 · 재시도) · Titan 임베딩
│       │   └── factory.py       # 실제 연동 서비스로 Providers / Deps 조립
│       ├── core/
│       │   ├── config.py        # .env 로드 · Bedrock 설정
│       │   ├── constants.py     # 공통 표시 문구·키
│       │   └── geo.py           # 거리 계산
│       └── tests/               # pytest 테스트
├── data/                          # 사용한 문서·데이터
│   └── tourapi_categories.json    # TourAPI 분류 코드표 (cat3 → 이름)
├── evaluation/                    # 인-아웃 세트와 자체 평가 결과
│   ├── test_queries.csv           # 인-아웃 세트 25건 (docs/evaluation.md)
│   ├── run_eval.py                # 인-아웃 세트 실행 · 채점 · 보고서 생성
│   ├── results/                   # 차수별 결과 원본 (JSON)
│   ├── round1_report.md           # 1차 자체 평가 결과 (12/20)
│   └── round2_report.md           # 2차 자체 평가 결과 (22/25)
├── docs/                          # 개발 문서
│   ├── retrospective.md           # 트라이앤에러 회고
│   └── dev-log.md                 # 개발 상세 기록 (시간순)
├── SERVICE.md                     # 서비스 스펙
├── requirements.txt               # 백엔드 Python 의존성
├── pytest.ini                     # 테스트 설정 (pythonpath = src)
└── README.md
```

## 참고
- 백엔드 모듈은 `src`를 기준으로 import한다 (`from backend.agent import ...`). 서버 실행 시 `--app-dir src`를 준다.
- 과제 지정 위치인 `agent.py`(메인 에이전트 그래프), `tools.py`(도메인 도구), `retriever.py`(RAG)는 `backend/` 바로 아래에 둔다.
- 의존 방향: `agent.py` → `supervisor/` → `agents/` → `tools.py` · `prompts/` · `core/`. `integrations/`는 `tools.Providers`의 실제 구현이고, `factory.py`만 이를 조립한다.
- 프론트엔드 의존 방향: `App.tsx` → `features/` → `components/ui/` → `components/base/`. 아래 계층은 위 계층을 import하지 않는다.
- API 키는 저장소 루트의 `.env`에만 두며 git에 올리지 않는다.
