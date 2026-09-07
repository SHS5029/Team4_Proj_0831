"""토론 입력을 정규화하는 외부 연결 없는 규칙."""

from __future__ import annotations

import re
import unicodedata

from backend.app.game_engine.errors import RuleViolation

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_speech(text: str) -> str:
    """제어문자를 제거하고 Unicode NFC·공백·길이 규칙을 적용한다."""

    normalized = unicodedata.normalize("NFC", str(text))
    normalized = _CONTROL_RE.sub(" ", normalized)
    normalized = " ".join(normalized.split())
    if not 1 <= len(normalized) <= 200:
        raise RuleViolation("SPEECH_LENGTH_INVALID")
    return normalized

