"""완료·실패 게임의 결과 화면."""

from __future__ import annotations

from typing import Any

import streamlit as st

RESULT_PAGE_CSS = """
<style>
:root {
  --result-blue: #2468ed;
  --result-dark: #071426;
  --result-ink: #172033;
  --result-muted: #65728b;
  --result-border: #d9e2ef;
  --result-green: #16864d;
}
[data-testid="stAppViewContainer"] { color: var(--result-ink); background: #f4f7fb; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] {
  width: min(100%, 1280px); max-width: 1280px; padding: 0 1.4rem 3rem;
}
.result-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: 4.2rem; margin: 0 -1.4rem 1.25rem; padding: 0 1.5rem;
  color: #fff; background: var(--result-dark); border-bottom: 1px solid #24324c;
}
.result-brand { font-size: 1.55rem; font-weight: 850; letter-spacing: -.05em; }
.result-status {
  display: inline-flex; align-items: center; gap: .4rem; margin-left: 1rem;
  padding: .42rem .7rem; border: 1px solid #2b3b57; border-radius: .55rem;
  color: #d8e2f3; font-size: .78rem;
}
.result-status::before {
  content: ""; width: .45rem; height: .45rem; border-radius: 50%; background: #31c477;
}
.result-settings {
  padding: .55rem .8rem; border: 1px solid #2b3b57; border-radius: .5rem;
  color: #d8e2f3; font-size: .82rem;
}
[class*="st-key-result-hero"] {
  min-height: 15.5rem; display: grid; position: relative; overflow: hidden;
  padding: 2rem !important; align-content: center; border: 1px solid #315886 !important;
  border-radius: .85rem !important; color: #fff !important;
  background: radial-gradient(circle at 52% 72%, #ffe5a0 0 7%, transparent 8%),
              linear-gradient(165deg, #17406f, #5c88bf 62%, #efad75) !important;
}
[class*="st-key-result-hero"]::after {
  content: "🤖  🕵️  🤖  🤖  🤖  🤖"; position: absolute; right: 1.5rem; bottom: 1rem;
  color: #fff; font-size: clamp(1.1rem, 2.5vw, 2rem); letter-spacing: .35rem;
}
[class*="st-key-result-hero"] h1,
[class*="st-key-result-hero"] h2,
[class*="st-key-result-hero"] p { position: relative; z-index: 1; color: #fff !important; }
[class*="st-key-result-summary"] {
  min-height: 15.5rem; padding: 1.1rem !important;
  border: 1px solid var(--result-border) !important;
  border-radius: .85rem !important; background: #fff !important;
  box-shadow: 0 .5rem 1.5rem rgba(20, 42, 81, .05);
}
[class*="st-key-result-player-"] {
  min-height: 8.5rem; padding: .9rem !important; border: 1px solid var(--result-border) !important;
  border-radius: .7rem !important; background: #fff !important;
}
[class*="st-key-result-records"] {
  margin-top: 1rem; padding: .9rem !important; border: 1px solid var(--result-border) !important;
  border-radius: .75rem !important; background: #fff !important;
}
[class*="st-key-result-night-"],
[class*="st-key-result-vote-"] {
  margin-bottom: .55rem; padding: .7rem .8rem !important;
  border: 1px solid #e0e7f1 !important; border-radius: .6rem !important;
  background: #f9fbfe !important;
}
[class*="st-key-result-actions"] { margin-top: 1rem; }
[class*="st-key-result-actions"] [data-testid="stButton"] button {
  min-height: 3rem; font-weight: 750;
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 0 .8rem 2rem; }
  .result-header { margin: 0 -.8rem 1rem; padding: 0 .9rem; }
  [class*="st-key-result-hero"], [class*="st-key-result-summary"] { min-height: auto; }
  [class*="st-key-result-hero"]::after { opacity: .45; }
}
</style>
"""

ROLE_PRESENTATION = {
    "MAFIA": ("마피아", "🥷", "🔴"),
    "DETECTIVE": ("탐정", "🕵️", "🔵"),
    "DOCTOR": ("의사", "🩺", "🟢"),
    "CITIZEN": ("시민", "🧑", "⚪"),
}

WINNER_PRESENTATION = {
    "CITIZEN": ("시민 진영 승리", "모든 마피아를 찾아냈습니다!"),
    "MAFIA": ("마피아 진영 승리", "마피아가 마을을 장악했습니다."),
}

WIN_REASON_LABELS = {
    "ALL_MAFIA_ELIMINATED": "모든 마피아 처형",
    "MAFIA_PARITY": "마피아와 시민 수 동률",
    "FINAL_MAFIA_SELECTED": "최종 지목으로 마피아 발견",
    "FINAL_NON_MAFIA_SELECTED": "최종 지목 실패",
}


def render(snapshot: dict[str, Any]) -> None:
    """COMPLETED는 Backend result만 상세 표시하고 FAILED는 공개 안내로 제한한다."""

    # Backend가 확정한 result만 역할·행동·투표 공개의 근거로 사용한다. Front는
    # public event나 생존자 수를 조합해 승패 또는 숨은 역할을 다시 판정하지 않는다.
    game = snapshot.get("game") if isinstance(snapshot.get("game"), dict) else {}
    scenario = snapshot.get("scenario") if isinstance(snapshot.get("scenario"), dict) else {}
    st.markdown(RESULT_PAGE_CSS, unsafe_allow_html=True)
    st.markdown(
        '<header class="result-header"><div><span class="result-brand">게임 종료</span>'
        '<span class="result-status">연결됨</span></div>'
        '<span class="result-settings">⚙&nbsp; 설정</span></header>',
        unsafe_allow_html=True,
    )

    if game.get("status") != "COMPLETED":
        _render_failed(scenario=scenario)
        return
    result = snapshot.get("result")
    if not isinstance(result, dict):
        st.error("결과 정보를 확인할 수 없어요.")
        st.info("홈에서 게임 상태를 다시 확인해 주세요.")
        _render_actions(show_feedback=False)
        return

    winner_title, winner_caption = _winner_presentation(result.get("winner"))
    hero_col, summary_col = st.columns([1.4, 1])
    with hero_col:
        with st.container(key="result-hero", border=True):
            st.markdown(f"# {winner_title}")
            st.markdown(f"### {winner_caption}")
            st.caption(str(scenario.get("title", "AI 마피아 게임")))
    with summary_col:
        _render_summary(game=game, result=result)

    _render_players(result=result)
    _render_records(result=result)
    _render_actions(show_feedback=True)


def _render_summary(*, game: dict[str, Any], result: dict[str, Any]) -> None:
    """Backend 결과의 진행 횟수·생존자·마지막 투표 정보를 요약한다."""

    players = _objects(result.get("players"))
    survivor_count = sum(1 for player in players if player.get("alive"))
    round_count = _round_count(game=game, result=result)
    with st.container(key="result-summary", border=True):
        st.markdown("### 게임 요약")
        round_col, survivor_col, vote_col = st.columns(3)
        round_col.metric("🚩 진행 라운드", round_count)
        survivor_col.metric("👥 생존자", survivor_count)
        vote_col.metric("🗳️ 결정 단계", _decisive_label(game=game, result=result))
        st.divider()
        st.success("이 결과는 서버에서 확인되었습니다.")
        finished_at = result.get("finished_at")
        if isinstance(finished_at, str):
            st.caption(f"완료 시간: {_display_timestamp(finished_at)}")
        reason = WIN_REASON_LABELS.get(str(result.get("win_reason")), "게임 종료 조건 충족")
        st.caption(f"종료 이유: {reason}")


def _render_players(*, result: dict[str, Any]) -> None:
    """종료 result에 공개된 전체 player 역할과 탈락 상태를 카드로 표시한다."""

    players = _objects(result.get("players"))
    st.markdown("## 전체 역할")
    if not players:
        st.info("표시할 최종 플레이어 정보가 없습니다.")
        return
    for row_start in range(0, len(players), 6):
        row = players[row_start : row_start + 6]
        columns = st.columns(len(row))
        for offset, player in enumerate(row):
            index = row_start + offset
            role_name, role_icon, role_marker = ROLE_PRESENTATION.get(
                str(player.get("role")),
                ("확인 중", "❔", "⚪"),
            )
            with columns[offset]:
                with st.container(key=f"result-player-{index}", border=True):
                    st.markdown(f"### {role_icon}")
                    st.markdown(f"**{str(player.get('display_name', '플레이어'))}**")
                    st.write(f"{role_marker} {role_name}")
                    status, detail = _player_status(player)
                    if status == "생존":
                        st.success(status)
                    else:
                        st.error(status)
                    if detail:
                        st.caption(detail)


def _render_records(*, result: dict[str, Any]) -> None:
    """result의 밤·투표 확정값을 이름으로 변환해 접을 수 있는 기록으로 표시한다."""

    players = _objects(result.get("players"))
    player_names = {
        str(player.get("player_id")): str(player.get("display_name", "플레이어"))
        for player in players
    }
    with st.container(key="result-records", border=True):
        with st.expander("▣ 게임 기록 보기", expanded=True):
            night_col, vote_col = st.columns(2)
            with night_col:
                st.markdown("#### 밤별 주요 기록")
                nights = _objects(result.get("nights"))
                if not nights:
                    st.caption("확정된 밤 기록이 없습니다.")
                for index, night in enumerate(nights):
                    with st.container(key=f"result-night-{index}", border=True):
                        _render_night_record(night=night, player_names=player_names)
            with vote_col:
                st.markdown("#### 투표별 주요 기록")
                votes = _objects(result.get("votes"))
                if not votes:
                    st.caption("확정된 투표 기록이 없습니다.")
                for index, vote in enumerate(votes):
                    with st.container(key=f"result-vote-{index}", border=True):
                        _render_vote_record(vote=vote, player_names=player_names)
            event_ids = result.get("public_event_ids")
            if isinstance(event_ids, list):
                st.caption(f"서버에서 확정된 공개 이벤트: {len(event_ids)}건")


def _render_night_record(*, night: dict[str, Any], player_names: dict[str, str]) -> None:
    """밤 결과에서 공개가 확정된 최종 대상과 사망자만 요약한다."""

    st.markdown(f"**🌙 밤 {night.get('round', '-')}**")
    attack_name = _player_name(night.get("resolved_attack_target_player_id"), player_names)
    protect_name = _player_name(night.get("protect_player_id"), player_names)
    killed_name = _player_name(night.get("killed_player_id"), player_names)
    st.write(f"공격 대상: {attack_name or '없음'}")
    st.write(f"보호 대상: {protect_name or '없음'}")
    st.write(f"사망자: {killed_name or '없음'}")
    investigations = night.get("investigations")
    if isinstance(investigations, list):
        st.caption(f"확정된 조사 기록: {len(investigations)}건")


def _render_vote_record(*, vote: dict[str, Any], player_names: dict[str, str]) -> None:
    """투표 결과의 단계·집계·탈락자만 표시하고 Front에서 결과를 재판정하지 않는다."""

    phase = _phase_label(str(vote.get("phase", "")))
    st.markdown(f"**☀️ {phase} · 라운드 {vote.get('round', '-')}**")
    eliminated_name = _player_name(vote.get("eliminated_player_id"), player_names)
    st.write(f"탈락자: {eliminated_name or '없음'}")
    counts = vote.get("counts")
    if isinstance(counts, list):
        for count in counts:
            if not isinstance(count, dict):
                continue
            target_name = _player_name(count.get("target_player_id"), player_names)
            vote_count = count.get("vote_count")
            if target_name and isinstance(vote_count, int):
                st.caption(f"{target_name}: {vote_count}표")


def _render_actions(*, show_feedback: bool) -> None:
    """결과를 변경하지 않는 피드백·새 게임·홈 이동 CTA를 제공한다."""

    with st.container(key="result-actions"):
        columns = st.columns(3 if show_feedback else 2)
        next_index = 0
        if show_feedback:
            if columns[0].button(
                "▣ 게임별 피드백",
                key="result.feedback",
                type="primary",
                use_container_width=True,
            ):
                st.session_state["navigation.page"] = "game_feedback"
                st.rerun()
            next_index = 1
        if columns[next_index].button(
            "새 게임",
            key="result.new_game",
            use_container_width=True,
        ):
            st.session_state["navigation.page"] = "create"
            st.session_state.pop("game.game_id", None)
            st.rerun()
        if columns[next_index + 1].button(
            "⌂ 홈으로",
            key="result.home",
            use_container_width=True,
        ):
            st.session_state["navigation.page"] = "home"
            st.session_state.pop("game.game_id", None)
            st.rerun()
        st.caption("게임 기록과 결과는 설정에서 다시 확인할 수 있습니다.")


def _render_failed(*, scenario: dict[str, Any]) -> None:
    """FAILED 상태에서는 전체 역할이나 미확정 결과를 공개하지 않는다."""

    st.error("게임을 완료하지 못했어요.")
    st.subheader(str(scenario.get("title", "게임 결과")))
    st.info("마지막으로 확인된 공개 상태만 표시합니다. 게임 결과를 복구할 수 없습니다.")
    _render_actions(show_feedback=False)


def _winner_presentation(value: Any) -> tuple[str, str]:
    """Backend winner enum을 결과 화면의 고정 제목과 설명으로 변환한다."""

    return WINNER_PRESENTATION.get(str(value), ("게임 종료", "서버에서 최종 결과를 확정했습니다."))


def _player_status(player: dict[str, Any]) -> tuple[str, str | None]:
    """결과에 포함된 alive·eliminated field만 사용해 최종 상태를 표시한다."""

    if player.get("alive"):
        return "생존", None
    phase = str(player.get("eliminated_phase", ""))
    status = "처형됨" if phase in {"DAY_VOTE", "REVOTE", "FINAL_ACCUSATION"} else "사망"
    round_number = player.get("eliminated_round")
    detail = f"{_phase_label(phase)} · 라운드 {round_number}" if round_number is not None else None
    return status, detail


def _round_count(*, game: dict[str, Any], result: dict[str, Any]) -> int:
    """결과 배열에 기록된 최대 round를 표시용 진행 횟수로 사용한다."""

    rounds = [game.get("round", 0)]
    rounds.extend(item.get("round", 0) for item in _objects(result.get("nights")))
    rounds.extend(item.get("round", 0) for item in _objects(result.get("votes")))
    return max((value for value in rounds if isinstance(value, int)), default=0)


def _decisive_label(*, game: dict[str, Any], result: dict[str, Any]) -> str:
    """마지막 확정 투표 단계 또는 Backend 종료 이유를 결정 단계로 표시한다."""

    votes = _objects(result.get("votes"))
    if votes:
        phase = _phase_label(str(votes[-1].get("phase", "")))
        return f"낮 {game.get('day_number', '-')}일차 · {phase}"
    return WIN_REASON_LABELS.get(str(result.get("win_reason")), "종료 조건")


def _phase_label(phase: str) -> str:
    """결과에 허용된 투표·탈락 phase enum을 짧은 한국어로 변환한다."""

    return {
        "NIGHT_ACTION": "밤 행동",
        "DAY_VOTE": "낮 투표",
        "REVOTE": "재투표",
        "FINAL_ACCUSATION": "최종 지목",
    }.get(phase, "게임 진행")


def _player_name(player_id: Any, player_names: dict[str, str]) -> str | None:
    """result player 식별자가 있을 때만 공개 이름으로 변환한다."""

    if player_id is None:
        return None
    return player_names.get(str(player_id))


def _objects(value: Any) -> list[dict[str, Any]]:
    """결과 배열에서 object 항목만 원래 순서대로 보존한다."""

    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _display_timestamp(value: str) -> str:
    """RFC 3339 문자열을 값 손실 없이 읽기 쉬운 표시로만 변환한다."""

    return value.replace("T", " ").removesuffix("Z")
