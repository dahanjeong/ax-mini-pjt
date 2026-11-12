"""Shared labels and keys used across agents, cards and the supervisor."""

FAIL = "정보를 불러오지 못함"
UNKNOWN = "정보 없음"
NO_REVIEW = "후기 정보 없음"
NO_PREFERENCE_EVIDENCE = "취향과 맞는다는 근거를 찾지 못했어요"   # preference level without evidence sentences
NO_DUST = "미세먼지 예보 없음"

FACILITY_KEYS = ("nursing_room", "stroller_rental", "parking")
SUIT_RANK = {"적합": 0, "보통": 1, "부적합": 2}

# drive-time check (Kakao Mobility directions) on the radius-filtered picks
DRIVE_CONFIRMED = "확인됨"
DRIVE_UNVERIFIED = "이동시간 확인 필요"
