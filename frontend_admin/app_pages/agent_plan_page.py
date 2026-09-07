"""RAG 기반 운영 에이전트의 설계 방향을 검토하는 관리자 화면."""

from __future__ import annotations

import streamlit as st
from frontend_admin.core.api_client import AdminApiError


AGENT_PLAN_CSS = """
<style>
.agent-plan-banner { padding:1rem 1.15rem; border:1px solid #d8c9ff; border-radius:.85rem; background:#f2edff; color:#2b1850; }
.agent-plan-banner strong { color:#4b237a; }
.agent-plan-flow { min-height:8.5rem; padding:1rem; border:1px solid #e1e4ed; border-radius:.8rem; background:#fff; box-shadow:0 8px 20px rgba(25,35,70,.05); }
.agent-plan-number { display:inline-flex; width:1.7rem; height:1.7rem; align-items:center; justify-content:center; border-radius:50%; color:#fff; background:#4b237a; font-weight:800; }
.agent-plan-flow h4 { margin:.7rem 0 .35rem; color:#172033; font-size:1rem; }
.agent-plan-flow p { margin:0; color:#4f5b73; font-size:.88rem; line-height:1.55; }
.agent-plan-example { padding:1rem 1.1rem; border-left:4px solid #6d4aff; border-radius:.6rem; background:#f7f8fc; color:#172033; line-height:1.65; }
.agent-plan-example strong { color:#4b237a; }
[data-testid="stTable"] td, [data-testid="stTable"] th { color:#172033 !important; background:#fff !important; }
</style>
"""


def render(*, synthetic: bool = False, client=None) -> None:
    """관리자용 운영 에이전트의 계획과 안전한 승인 자료 검색을 표시한다."""

    st.markdown(AGENT_PLAN_CSS, unsafe_allow_html=True)
    st.subheader("운영 에이전트 계획")
    st.markdown('<div class="admin-status-label">● 1단계 구현 · 근거 검색 연결</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="agent-plan-banner"><strong>관리자 질문에 맞는 근거 있는 요약 도우미</strong><br>'
        '정보를 무작정 뿌리는 에이전트가 아니라, 승인된 운영 자료를 찾아 출처와 함께 짧게 답하는 '
        'read-only 기능을 목표로 합니다.</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "가상 승인 자료로 검색 흐름을 확인하는 화면입니다." if synthetic
        else "승인 자료 검색만 실행하며, 게임·문서 데이터 변경이나 자동 조치는 실행하지 않습니다."
    )

    overview = st.columns(4)
    for column, label, value in zip(
        overview,
        ("자료 범위", "검색 방식", "답변 원칙", "자동 조치"),
        ("승인 자료만", "키워드 + 벡터", "근거·신뢰도", "차단"),
        strict=True,
    ):
        column.metric(label, value)

    st.markdown("#### 권장 동작 흐름")
    flow_steps = (
        ("1", "자료 수집·정제", "피드백·공개 게임 요약·운영 문서를 권한과 버전별로 정리합니다."),
        ("2", "벡터화·검색", "PostgreSQL + pgvector에 임베딩하고 키워드 검색과 유사도 검색을 함께 사용합니다."),
        ("3", "근거 답변", "질문에 필요한 부분만 요약하고 출처 ID·신뢰도·근거 부족 여부를 함께 반환합니다."),
        ("4", "감사·보호", "모든 조회를 기록하고 쓰기·삭제·강제 종료 같은 자동 조치는 허용하지 않습니다."),
    )
    flow_columns = st.columns(4)
    for column, (number, title, description) in zip(flow_columns, flow_steps, strict=True):
        with column:
            st.markdown(
                f'<div class="agent-plan-flow"><span class="agent-plan-number">{number}</span>'
                f'<h4>{title}</h4><p>{description}</p></div>',
                unsafe_allow_html=True,
            )

    st.markdown("#### 승인 자료에게 질문하기")
    with st.container(border=True):
        st.caption("검색 결과는 근거 문장과 신뢰도를 함께 보여 줍니다. 근거가 부족하면 추측하지 않습니다.")
        with st.form("admin.agent.query"):
            question = st.text_input(
                "관리자 질문",
                value="최근 낮은 평점에서 반복되는 문제는 무엇인가요?",
                key="admin.agent.question",
            )
            source_types = st.multiselect(
                "검색 자료",
                options=["피드백", "공개 게임 요약", "운영 문서"],
                default=["피드백", "공개 게임 요약", "운영 문서"],
                key="admin.agent.sources",
            )
            submitted = st.form_submit_button("근거 검색", key="admin.agent.search", type="primary")
        if submitted:
            if client is None:
                st.error("관리자 API 연결이 준비되지 않았습니다.")
            else:
                source_map = {"피드백": "FEEDBACK", "공개 게임 요약": "GAME_SUMMARY",
                              "운영 문서": "OPERATIONS_DOC"}
                try:
                    response = client.insights_query(
                        question,
                        source_types=[source_map[item] for item in source_types],
                        top_k=5,
                    )
                    result = response.get("data")
                    if not isinstance(result, dict):
                        raise ValueError("INVALID_RESPONSE")
                    st.session_state["admin.agent.result"] = result
                except AdminApiError as exc:
                    # API client는 공개 오류 코드만 관리 화면으로 전달하므로
                    # DB 접속 문자열이나 Provider 원문은 화면에 표시하지 않는다.
                    st.session_state.pop("admin.agent.result", None)
                    if exc.code == "DEPENDENCY_UNAVAILABLE":
                        st.error(
                            "승인 자료 색인이 아직 준비되지 않았습니다. "
                            "DB 담당자가 pgvector 확장과 005 migration을 적용한 뒤 색인 명령을 실행해 주세요."
                        )
                    else:
                        st.error("승인 자료 검색 권한 또는 요청을 확인해 주세요.")
                except ValueError:
                    st.session_state.pop("admin.agent.result", None)
                    st.error("질문 형식이 올바르지 않습니다. 3자 이상 입력해 주세요.")

        result = st.session_state.get("admin.agent.result")
        if isinstance(result, dict):
            confidence = result.get("confidence", "LOW")
            evidence_state = "근거 충분" if result.get("has_sufficient_evidence") else "추가 확인 필요"
            st.markdown(f"**답변 · {confidence} · {evidence_state}**")
            st.markdown(f'<div class="agent-plan-example">{result.get("answer", "")}</div>', unsafe_allow_html=True)
            sources = result.get("sources", [])
            if isinstance(sources, list) and sources:
                st.markdown("**사용한 근거**")
                st.dataframe(
                    [{"자료 유형": row.get("source_type", ""), "자료 ID": row.get("source_id", ""),
                      "제목": row.get("title", ""), "근거 문장": row.get("snippet", ""),
                      "점수": row.get("score", 0)} for row in sources if isinstance(row, dict)],
                    hide_index=True,
                )

    st.markdown("#### 관리자 화면에서 보일 답변 형태")
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**질문 예시**")
            st.markdown('<div class="agent-plan-example">최근 평점이 낮은 피드백에서 반복되는 문제는 무엇인가요?</div>', unsafe_allow_html=True)
            st.caption("실제 질문은 위의 승인 자료 검색에서 한 번에 실행할 수 있습니다.")
    with right:
        with st.container(border=True):
            st.markdown("**답변 예시**")
            st.markdown(
                '<div class="agent-plan-example"><strong>요약</strong><br>'
                '최근 낮은 평점 의견에서는 사건 설명의 이해도와 토론 진행 안내가 반복적으로 언급되었습니다.'
                '<br><br><strong>근거</strong> feedback:2026-09-07-001 · 운영문서:v1.2<br>'
                '<strong>신뢰도</strong> 중간 · 추가 확인 필요</div>',
                unsafe_allow_html=True,
            )

    st.markdown("#### 데이터 경계")
    allowed, excluded = st.columns(2)
    with allowed:
        with st.container(border=True):
            st.markdown("**검색 허용**")
            st.markdown("- 사용자 피드백의 공개 목록 필드\n- 종료 게임의 공개 요약\n- 승인된 운영 문서와 API 명세\n- 기간·시나리오·이슈 유형 같은 필터 메타데이터")
    with excluded:
        with st.container(border=True):
            st.markdown("**검색 제외**")
            st.markdown("- API 키·DB 비밀번호·토큰\n- 개인 식별 정보와 원문 인증 claim\n- 진행 중 게임의 역할·개별 행동·private context\n- LLM prompt 원문과 모델 내부 추론 과정")

    st.markdown("#### 단계별 도입 계획")
    st.table(
        {
            "단계": ["1. 자료 기반", "2. 검색 품질", "3. 답변 API", "4. 운영 검증"],
            "관리자에게 보이는 결과": ["자료·권한·버전 확인", "유사 피드백과 출처 목록", "요약·근거·신뢰도", "품질 지표와 감사 이력"],
            "상태": ["계획", "계획", "계획", "계획"],
        }
    )
    st.info(
        "현재는 고정 차원 로컬 임베딩과 PostgreSQL pgvector 혼합 검색을 사용합니다. 외부 LLM 호출, "
        "자동 데이터 변경, 문서 삭제는 연결하지 않았습니다.",
        icon=":material/info:",
    )
