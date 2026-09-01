"""후속 관리자 기능을 위한 독립 실행 가능한 최소 Streamlit 진입점."""

import streamlit as st


def main() -> None:
    """관리자 업무 기능이 아직 비활성 상태임을 명확히 표시한다."""

    st.set_page_config(page_title="관리자", page_icon="🛠️", layout="centered")
    st.title("관리자 화면")
    st.info("관리자 업무 기능은 후속 구현 단계에서 제공됩니다.")
    st.caption("현재 앱은 사용자 Frontend와 분리된 실행 경계만 제공합니다.")


if __name__ == "__main__":
    main()
