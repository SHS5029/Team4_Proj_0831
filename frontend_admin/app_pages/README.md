# 관리자 조회 화면

`dashboard_page.py`는 운영 지표, `game_list_page.py`는 상태·단계 필터와 최근 게임,
`game_detail_page.py`는 비공개 필드를 제거한 상세를 표시합니다. 진입점은 Backend의
관리자 metrics 200 응답을 확인한 뒤 이 화면을 호출하며, 모든 기능은 read-only입니다.

상세 선택은 진입점에서 공개 `game_id` 주소로 유지하며 관리자 UUID는 주소에 넣지
않습니다. 관리자 진입·복구 방법과 검증 명령은 [관리자 README](../README.md)를 따릅니다.
