"""비밀정보를 기록하지 않는 Backend 기본 로깅 설정."""

import logging


def configure_logging() -> None:
    """애플리케이션이 별도 설정을 주입하지 않은 경우에만 기본 포맷을 적용한다."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
