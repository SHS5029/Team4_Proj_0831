"""향후 관리자 인증과 권한 판정을 둘 fail-closed 세션 경계."""

ADMIN_ACCESS_SESSION_KEY = "admin-access-granted"


def has_admin_access(value: object) -> bool:
    """명시적인 불리언 True만 관리자 접근 허용으로 해석한다."""

    return value is True
