# 프론트엔드 컴포넌트

`src/frontend/src`의 UI는 세 계층으로 나뉜다. 의존 방향은 한쪽으로만 흐른다.

```
App.tsx  →  features/  →  components/ui/  →  components/base/
```

| 계층 | 하는 일 | 하지 않는 일 |
|---|---|---|
| `components/base/` | 동작 · HTML 시맨틱 · 접근성(role, aria). 상태는 `data-*` 속성으로 드러낸다. 모든 부품이 `className`(또는 `classNames` 슬롯)을 받는다. | CSS import, 색·크기 결정, 도메인 타입 사용 |
| `components/ui/` | base를 감싸 디자인 토큰(`tokens.css`) 기반 스타일을 입힌다. 컴포넌트마다 같은 이름의 `.css`를 직접 import한다. 변형은 `variant` · `size` · `tone` props로 고른다. | 백엔드 호출, 도메인 규칙 |
| `features/` | 도메인 데이터를 ui 컴포넌트로 그린다. 도메인 전용 스타일은 feature 폴더의 `.css`에 둔다. | 다른 feature의 내부 파일 import (`index.ts`로만) |

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

## 새 컴포넌트를 만들 때
1. 동작·접근성이 있으면 `base/`에 스타일 없이 만들고, 상태는 `data-*`로 드러낸다.
2. `ui/`에서 base를 감싸 클래스와 `.css`를 붙인다. 색·간격은 `tokens.css` 변수만 쓴다.
3. 같은 선택자 우선순위끼리 덮어써야 하면(예: `Tile.css`가 `.stock`의 padding을 덮음) 덮는 쪽 컴포넌트가 덮이는 쪽을 먼저 import한다.
4. 각 계층의 `index.ts`에 export를 추가한다.
5. CSS 주석 안에 `*/`가 생기는 글로브(`features/*/*.css`)를 쓰지 않는다 — 주석이 닫혀 빌드가 깨진다.
