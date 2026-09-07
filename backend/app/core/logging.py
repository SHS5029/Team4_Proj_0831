"""비밀정보를 기록하지 않는 Backend 기본 로깅 설정."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock


_progress_lock = RLock()


class _QuietRotatingFileHandler(RotatingFileHandler):
    """디스크·회전 실패 시 원문 record나 예외를 stderr에 재출력하지 않는다."""

    def handleError(self, record: logging.LogRecord) -> None:
        pass


def progress_logger() -> logging.Logger:
    """터미널·5 MiB 순환 파일을 한 번만 구성하고 파일 장애를 격리한다."""

    with _progress_lock:
        logger = logging.getLogger("backend.game_progress")
        if getattr(logger, "_progress_configured", False):
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False
        terminal = logging.StreamHandler()
        terminal.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(terminal)
        try:
            directory = Path(__file__).resolve().parents[2] / "logs"
            directory.mkdir(exist_ok=True)
            handler = _QuietRotatingFileHandler(directory / "game-progress.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        except OSError:
            # 로그 디렉터리가 읽기 전용이어도 게임의 저장·진행은 계속 허용한다.
            pass
        logger._progress_configured = True
        return logger


def configure_logging() -> None:
    """애플리케이션이 별도 설정을 주입하지 않은 경우에만 기본 포맷을 적용한다."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    progress_logger()
