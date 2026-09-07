"""Streamlit Python을 점유하지 않는 browser SSE component 계약을 검증한다."""

from pathlib import Path


def test_sse_component_uses_browser_fetch_and_abortable_lifecycle() -> None:
    """SSE 수신이 JS fetch와 AbortController 안에서 수행되는지 확인한다."""

    source = (
        Path(__file__).parents[1] / "components" / "browser_components" / "sync" / "index.js"
    ).read_text(encoding="utf-8")
    assert "fetch(url" in source
    assert "new AbortController()" in source
    assert 'setStateValue("status"' not in source
    assert '"Last-Event-ID": String(lastSequence)' in source
    assert "await wait(1000)" in source
    assert "hasOperations" in source
    assert "hasCursorAdvance" in source
    assert "controller.abort()" in source
