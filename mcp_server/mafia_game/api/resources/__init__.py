"""FastMCP Resource 등록 모듈."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mafia_game.integrations.engine_http import BackendContextClient


# 배경 서사를 역할 증거로 혼동하지 않도록 모델에는 실행 규칙을 고정 안내한다.
GAME_RULES = (
    "시민 진영은 마피아 전원을 제거하면 승리한다. 생존 마피아 수가 비마피아 수 이상이면 마피아가 승리한다.",
    "첫날에는 좌석 순서로 한 번씩 발언하고 처형 투표 없이 밤으로 간다. 둘째 날부터 토론 뒤 처형 투표를 한다. 전원 PASS일 때만 추가 한 순환이 있다.",
    "발언은 자기 차례에만 한다. 질문 후 상대 차례가 오지 않았다면 답하지 않았다는 이유로 회피라고 판단할 수 없다.",
    "밤에 마피아는 자신을 제외한 생존자 한 명을 선택한다. 동료 마피아의 신원은 제공되지 않는다. 두 선택이 갈리면 두 후보 중 하나를 결정적 RNG로 골라 한 명만 공격한다.",
    "마피아 한 명만 제출하면 그 선택을 사용한다. 전원 미제출이면 비마피아 생존자 중 한 명을 진영 단위로 자동 선택한다.",
    "의사는 자신을 포함한 생존자 한 명을 보호하며 연속 자기 보호도 가능하다. 탐정은 자신을 제외한 생존자 한 명을 조사해 마피아 여부만 확인한다.",
    "밤 행동은 동시에 확정된다. 그 밤 죽는 탐정의 조사와 의사의 보호도 유효하다. 최종 공격 대상과 보호 대상이 같으면 사망자가 없다. 무사망만으로 의사 신원이나 보호 성공을 확정할 수 없다.",
    "밤은 20초이며 첫 유효 선택은 바꿀 수 없다. 탐정·의사의 미제출은 자신을 제외한 후보 중 자동 선택된다. 실제 허용 대상과 마감은 turn과 Backend 판정이 우선이다.",
    "투표는 자신을 제외한 생존자 한 명에게 하며 기권하지 않는다. 30초 내 미제출은 자동 선택된다. 최다 득표 동률은 해당 후보끼리 재투표하고 재동률이면 처형하지 않는다.",
    "처형 역할은 즉시 공개되지만 밤 사망자의 역할은 종료 전 숨겨진다. 진행 중 개별 투표·타인의 밤 선택은 알 수 없다. 탐정 자칭과 그 조사 보고는 타인에게는 주장이다.",
    "사망자는 발언·투표·밤 행동을 할 수 없다. 다섯 번째 밤 이후에는 최종 토론·지목을 한다. 최다 지목이 마피아이면 시민 승리, 아니면 마피아 승리이며 동률은 결정적 RNG로 정한다.",
    "시나리오는 배경일 뿐 역할 판정 증거가 아니다. 공개 발언의 실제 모순, 확정 처형 역할, 본인 조사 결과를 비교하라. 없는 동선·시각·목격 사실을 만들지 말라.",
)


def model_context(payload: dict[str, Any]) -> dict[str, Any]:
    """운영 Resource에서 서사만 제외하고 원본·공개 이력·본인 조사 기록은 보존한다."""

    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    scope = payload.get("scope")
    if scope == "public":
        scenario = data.get("scenario")
        if not isinstance(scenario, dict):
            return payload
        return {**payload, "data": {**data,
            "scenario": {key: scenario[key] for key in ("scenario_id", "title") if key in scenario},
            "rules": list(GAME_RULES)}}
    if scope == "me":
        return {**payload, "data": {key: value for key, value in data.items()
                                    if key not in {"alibi", "observation"}}}
    return payload


def register_resources(mcp: FastMCP, backend: BackendContextClient) -> None:
    """공개 조회와 AI actor별 조회 URI를 등록하고 projection은 Backend에 위임한다."""

    @mcp.resource(
        "mafia://context/current/{game_id}/{user_id}",
        name="current_context",
        mime_type="application/json",
    )
    async def current_context(game_id: str, user_id: str) -> dict[str, Any]:
        """actor 없는 기존 URI는 Backend의 공개 scope만 읽는다."""

        return model_context(await backend.read_resource(
            f"mafia://context/current/{game_id}/{user_id}"
        ))

    @mcp.resource(
        "mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}",
        name="scoped_context",
        mime_type="application/json",
    )
    async def scoped_context(
        game_id: str, user_id: str, player_id: str, scope: str
    ) -> dict[str, Any]:
        """AI actor와 scope를 전달하고 권한·응답 데이터의 최종 판정은 Backend에 맡긴다."""

        return model_context(await backend.read_resource(
            f"mafia://context/scoped/{game_id}/{user_id}/{player_id}/{scope}"
        ))
