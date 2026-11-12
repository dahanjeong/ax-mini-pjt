# 프론트엔드 컴포넌트

`src/frontend/src`의 UI는 세 계층으로 나뉜다. 의존 방향은 한쪽으로만 흐른다.

```
App.tsx  →  features/  →  components/ui/  →  components/base/
```

| 계층 | 하는 일 | 하지 않는 일 |
|---|---|---|
| `components/base/` | 동작 · HTML 시맨틱 · 접근성(role, aria). 상태는 `data-*` 속성으로 드러낸다. 모든 부품이 `className`(또는 `classNames` 슬롯)을 받는다. | CSS import, 색·크기 결정, 도메인 타입 사용 |
| `components/ui/` | base를 감싸 디자인 토큰(`tokens.css`) 기반 스타일을 입힌다. 변형은 `variant` · `size` · `tone` props로 고른다. | 백엔드 호출, 도메인 규칙 |
| `features/` | 도메인 데이터를 ui 컴포넌트로 그린다. | 다른 feature의 내부 파일 import (`index.ts`로만) |

## 폴더 규칙

`src/` 루트에는 진입점 `main.tsx`와 화면 조립 `App.tsx`만 둔다. 나머지는 주인이 있는 폴더로 간다.

| 무엇 | 어디 |
|---|---|
| 전역 CSS (토큰 · 리셋 · 앱 셸) | `styles/` (`global.css`가 `tokens.css` · `base.css`를 불러옴) |
| 백엔드 요청·응답 타입 | `api/types/` (`api/index.ts`에서 export) |
| 화면 상태 모델 (예: `ChatMessage`) | 해당 feature의 `types/` |
| 표시용 순수 함수 (`format.ts`)와 테스트 | 쓰는 feature 폴더 (`features/place/format.ts`, `features/chat/format.ts`) |
| 테스트 | 대상 파일 옆 `*.test.ts` |

각 컴포넌트 폴더의 루트에는 컴포넌트(`.tsx`)와 `index.ts`만 둔다. 스타일과 Props 타입은 하위 폴더로 모은다.

```
components/ui/
├── Button.tsx …          # 컴포넌트
├── index.ts              # 컴포넌트 + 타입 re-export
├── styles/
│   ├── commonStyle.css   # 이 폴더의 여러 컴포넌트가 함께 쓰는 스타일
│   └── Button.css …      # 컴포넌트와 같은 이름
└── types/
    ├── commonType.ts     # 이 폴더의 여러 타입이 함께 쓰는 모양
    ├── Button.ts …       # 컴포넌트와 같은 이름 (Props 타입)
    └── index.ts
```

- `base/`는 스타일이 없으므로 `types/`만 있다.
- 컴포넌트는 자기 스타일 파일과, 쓰는 `commonStyle.css`를 직접 import한다. 같은 CSS를 여러 곳에서 import해도 번들에는 한 번만 들어간다.
- 새 타입은 처음부터 쓰지 말고 `Omit` · `Pick` · `commonType`의 헬퍼로 기존 타입에서 파생한다.

## 공통 타입 (`types/commonType.ts`)

| 폴더 | 타입 | 쓰는 곳 |
|---|---|---|
| base | `DivProps` | `Group`, `Bubble` |
| base | `ClassNames<Part>`: 부품별 className 슬롯 | `MessageForm`(`root/input/submit`), `DescriptionList`(`root/term/detail`) |
| base | `TonedProps<E>` = 요소 속성 + `tone` | `Badge`, `Callout` |
| base | `ValueProps` = `value` + `onValueChange` | `TextField`, `MessageForm` (`MessageForm`은 `Pick<TextFieldProps, "placeholder" \| "maxLength">`도 재사용) |
| ui | `WithTone<P, Tone>` = `Omit<P, "tone">` + 고정된 tone 집합 | `Badge`, `Callout` |
| ui | `StyledSlots<P>` = `Omit<P, "classNames">` + 루트 `className` | `Composer`, `DefinitionList` |
| ui | `Size`, `StatusTone`(`good` · `caution` · `bad`) | `Button`, `BadgeTone` |
| chat | `SendHandler`, `ChatState`(= `ReturnType<typeof useChat>`) | `TopBar`(`Pick<ChatState, "online" \| "canRestart">`), `ExampleList`, `Message` |
| chat | `ChatMessage`, `Choice`, `Role`(= ui `BubbleFrom`) | `useChat`, `format.ts`, `App` |
| place | `CardFieldProps<K>` = `Pick<PlaceCardData, K>`, `PresentField<K>` | `DriveInfo`, `FacilityGrid`, `PreferenceMatch` |

그 밖의 파생 예: `TileProps = Omit<ButtonProps, "variant" | "size">` + 타일 변형, ui `BubbleProps = Omit<BaseBubbleProps, "from">` + `from: Role`, `StatusPillProps = Omit<StatusProps, "inline">`.

## 공통 스타일 (`styles/commonStyle.css`)

| 폴더 | 내용 | 쓰는 곳 |
|---|---|---|
| ui | 색조 토큰 `--tint-good` · `--tint-caution` · `--tint-notice` · `--tint-bad` · `--tint-bad-strong` · `--tint-accent` | Badge, Callout, Bubble(오류), StatusPill, 편의시설 칸 |
| ui | `.pill` (둥근 라벨) | Badge, StatusPill |
| ui | `.soft-block` (작은 글씨 안내 블록) | Callout |
| ui | `.surface-paper` (떠 있는 종이 카드) | Hero, PlaceCard |
| ui | `.sticky-bar` (화면 위·아래 고정 바) | TopBar, Composer |
| chat | `.turn` (대화 한 턴 배치) | Message, PendingTurn |
| place | `.soft-cell` (옅은 둥근 칸) · `.muted-note` (작은 회색 메모) | 편의시설 칸, 취향 근거 인용 / 함께 있는 곳, 불러오지 못한 정보 |

## Base (`components/base`)

| 컴포넌트 | 담당하는 동작 | 노출 |
|---|---|---|
| `Button` | 기본 `type="button"` (폼 오제출 방지), ref 전달 | 모든 button 속성 |
| `TextField` | 제어 입력, 이벤트 대신 문자열을 넘김 (`onValueChange`) | ref |
| `MessageForm` | 빈 문자열·공백 전송 막기, 처리 중 전송 막기, 처리 중에도 입력창은 비활성화하지 않음(포커스 유지), `aria-busy` | `classNames.root/input/submit` |
| `Group` | `role="group"` 묶음 | `aria-label` / `aria-labelledby` |
| `Badge` | 인라인 라벨 | `data-tone` |
| `Bubble` | 말풍선 | `data-from`, `data-follow` |
| `Callout` | 본문과 구분되는 안내 블록 | `data-tone` |
| `Status` | `role="status"` 라이브 영역 | `inline`(span) |
| `LoadingDots` | 장식용 점, 스크린 리더에서 숨김 | `className`, `dotClassName` |
| `ExternalLink` | 새 탭 + `rel="noopener noreferrer nofollow"`, http(s)가 아니면 링크 대신 텍스트 | `isSafeHref()` |
| `DescriptionList` | `dl > dt/dd` 쌍 | `classNames.root/term/detail` |
| `cx` | className 합치기 | |

## UI (`components/ui`)

| 컴포넌트 | 쓰는 Base | 변형 |
|---|---|---|
| `Button` | `Button` | `variant`: `stock`(종이 카드) · `primary`(배 색, 전송) / `size`: `md` · `sm` |
| `Tile`, `TileGroup` | `Button`(ui) · `Group` | `variant`: `example` · `choice`(번호 칩, `leading`) |
| `Badge` | `Badge` | `tone`: `neutral` · `good` · `caution` · `bad` · `accent` · `muted` |
| `Bubble` | `Bubble` | `from`: `user` · `assistant` · `error`, `follow` |
| `Callout` | `Callout` | `tone`: `notice` · `warning` |
| `StatusPill` | `Status` | 서버 연결 끊김 등 |
| `TypingIndicator` | `LoadingDots` + `Bubble`(ui) | 처리 중 말풍선 (`prefers-reduced-motion`이면 깜빡임) |
| `Composer` | `MessageForm` | 하단 고정 입력바 |
| `DefinitionList` | `DescriptionList` | 실선으로 나눈 2열 |

## Features

| 폴더 | 컴포넌트 |
|---|---|
| `features/chat` | `TopBar`, `Hero`, `ExampleList`, `Message`, `PendingTurn`, `useChat`(대화·세션·서버 상태와 전송·재시작) |
| `features/place` | `PlaceCard`, `PlaceCardList`, `DriveInfo`, `FacilityGrid`, `PreferenceMatch`, `ReviewSources`, `tones.ts`(백엔드 값 → Badge tone) |

`hooks/`에는 화면 동작만 담는다: `useChatScroll`(처리 중 말풍선 / 새 답변 시작점으로 스크롤), `useFocusWhenSettled`(응답이 오면 입력창으로 포커스).

## API (`api/`)

백엔드 호출도 두 계층으로 나눈다. 화면 코드는 업무 계층만 부른다.

| 계층 | 파일 | 하는 일 |
|---|---|---|
| 라이브러리 | `api/http/client.ts` | axios 인스턴스(baseURL `http://localhost:8000`, 60초 타임아웃). `get` · `post` · `put` · `patch` · `del`이 응답 본문을 돌려주고, 실패하면 `HttpError`를 던진다. |
| 라이브러리 | `api/http/HttpError.ts` | 모든 실패를 하나로: `kind`(`network` · `timeout` · `http`), `status`, `data` |
| 업무 | `api/chat.ts` | `sendChat`, `checkHealth`. `HttpError`를 사용자에게 보일 문구로 바꿔 `ChatError`로 던진다 (연결 실패 / 422 / 그 밖의 서버 오류·타임아웃). |

새 도메인 API는 `api/<도메인>.ts`를 만들어 `http/`의 함수만 쓰고, `api/index.ts`에서 export한다.

## 새 컴포넌트를 만들 때
1. 동작·접근성이 있으면 `base/`에 스타일 없이 만들고, 상태는 `data-*`로 드러낸다. Props 타입은 `base/types/<이름>.ts`.
2. `ui/`에서 base를 감싸 클래스를 붙이고, 스타일은 `ui/styles/<이름>.css`, 타입은 `ui/types/<이름>.ts`에 둔다. 색·간격은 `tokens.css` 변수와 `--tint-*`만 쓴다.
3. 두 곳 이상에서 같은 선언이 나오면 그 폴더의 `commonStyle.css` / `commonType.ts`로 올린다.
4. 같은 선택자 우선순위끼리 덮어써야 하면(예: `Tile.css`가 `.stock`의 padding을 덮음) 덮는 쪽 컴포넌트가 덮이는 쪽을 먼저 import한다.
5. 각 계층의 `index.ts`(와 `types/index.ts`)에 export를 추가한다.
6. CSS 주석 안에 `*/`가 생기는 글로브(`features/*/*.css`)를 쓰지 않는다 — 주석이 닫혀 빌드가 깨진다.
