"""향후 관리자 인증과 권한 판정을 둘 fail-closed 세션 경계."""

ADMIN_ACCESS_SESSION_KEY = "admin-access-granted"
ADMIN_USER_ID_SESSION_KEY = "admin.user_id"
ADMIN_STORAGE_KEY = "ai_mafia_admin_user_id_v1"


def has_admin_access(value: object) -> bool:
    """명시적인 불리언 True만 관리자 접근 허용으로 해석한다."""

    return value is True
