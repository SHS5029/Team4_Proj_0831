"""외부 원문을 포함하지 않는 MCP session·Resource 경계의 폐쇄형 오류다."""


class AuthRequired(Exception):
    """필수 인증 header가 없거나 bearer 외형을 신뢰할 수 없음을 나타낸다."""


class BootstrapDenied(Exception):
    """인증 외형 확인 뒤 서명·claim·binding 검증이 거부됐음을 나타낸다."""


class ReplayDetected(Exception):
    """같은 bootstrap nonce가 현재 process에서 이미 소비 시도됐음을 나타낸다."""


class EngineConsumeDenied(Exception):
    """Engine 거부·장애·응답 계약 위반을 initialize 경계에서 단일화한다."""


class CapabilityDenied(Exception):
    """local allowlist 또는 Engine 403·404가 존재를 숨긴 거부임을 나타낸다."""


class DependencyUnavailable(Exception):
    """Engine 연결·timeout·rate limit·server 장애만 재시도 가능 경계로 분류한다."""


class UpstreamContractViolation(Exception):
    """Engine status·media type·JSON·binding·schema가 정본과 다름을 나타낸다."""
