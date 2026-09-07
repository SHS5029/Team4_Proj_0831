"""API 9.4의 여섯 필드만 구성하고 운영 sink 장애를 게임 흐름과 분리한다."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from uuid import UUID, uuid4

from mafia_game.ports.audit import AuditSink, AuditValue

AUDIT_SPAN_SCOPE_KEY = "mafia.audit_span"


class AuditOperation(Enum):
    """현재 runtime에 존재하는 경로만 나타내는 폐쇄형 작업 이름이다."""

    INITIALIZE = "INITIALIZE"
    BOOTSTRAP_CONSUME = "BOOTSTRAP_CONSUME"
    RESOURCE_LIST = "RESOURCE_LIST"
    RESOURCE_READ = "RESOURCE_READ"
    ENGINE_CONTEXT = "ENGINE_CONTEXT"
    SESSION_TEARDOWN = "SESSION_TEARDOWN"
    PROTOCOL_REQUEST = "PROTOCOL_REQUEST"


class AuditStatus(Enum):
    """상태 문자열에 외부 response나 exception이 섞이지 않도록 고정한다."""

    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditError(Enum):
    """공개 계약의 고정 오류 분류와 취소만 허용하고 원문 메시지는 받지 않는다."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    BOOTSTRAP_DENIED = "BOOTSTRAP_DENIED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SESSION_NOT_ACTIVE = "SESSION_NOT_ACTIVE"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    UPSTREAM_CONTRACT_VIOLATION = "UPSTREAM_CONTRACT_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CANCELLED = "CANCELLED"


def _safe_uuid(value: object) -> str:
    """UUID만 정규화하고 외부 객체의 문자열 변환 없이 새 추적 ID로 대체한다."""

    if type(value) is UUID:
        return str(value)
    if type(value) is str and len(value) == 36:
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value.lower():
                return str(parsed)
    return str(uuid4())


def _read_clock(clock: Callable[[], float]) -> float | None:
    """실패하거나 비유한 clock은 원문을 기록하지 않고 해당 측정만 폐기한다."""

    try:
        value = clock()
        if type(value) not in {int, float}:
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except Exception:
        # clock 장애도 gameplay 실패로 번지지 않는다. 취소 같은 BaseException은
        # 여기서 삼키지 않아 상위 task의 기존 취소·cleanup 동작을 유지한다.
        return None


class AuditRecorder:
    """기본 discard sink와 task별 UUID scope를 제공하는 감사 record 생성기다."""

    def __init__(
        self,
        sink: AuditSink | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._clock = clock
        # recorder마다 별도 ContextVar를 써 테스트·동시 app의 추적 ID를 섞지 않는다.
        self._ids: ContextVar[tuple[str, str] | None] = ContextVar("mafia_audit_ids", default=None)

    @contextmanager
    def context(
        self,
        *,
        request_id: object = None,
        correlation_id: object = None,
    ) -> Iterator[None]:
        """새 요청 scope의 검증된 UUID를 묶고 예외·취소 시에도 이전 scope를 복원한다."""

        # contextmanager의 generator frame도 with 종료까지 유지되므로 입력 인자
        # 자체를 안전한 값으로 치환해 잘못 전달된 header·exception 참조를 남기지 않는다.
        request_id = _safe_uuid(request_id)
        correlation_id = _safe_uuid(correlation_id)
        token = self._ids.set((request_id, correlation_id))
        try:
            yield
        finally:
            self._ids.reset(token)

    def start(self, operation: AuditOperation) -> AuditSpan:
        """현재 요청의 안전한 ID를 상속하되 raw HTTP/RPC 객체는 보관하지 않는다."""

        ids = self._ids.get()
        if ids is None:
            ids = (_safe_uuid(None), _safe_uuid(None))
        return AuditSpan(self, operation, ids, _read_clock(self._clock))

    def _emit(self, record: dict[str, AuditValue]) -> None:
        """허용 record의 복사본만 전달하고 sink 예외에는 대체 log나 파일을 만들지 않는다."""

        if self._sink is None:
            return
        try:
            self._sink.emit(dict(record))
        except Exception:
            # 원문 exception을 분류 문자열로 바꾸거나 다른 logger로 전달하지 않는다.
            # 운영 sink 장애의 외부 감시는 sink 소유자의 책임이며 게임 판정과 분리한다.
            return


class AuditSpan:
    """안전한 식별자와 시작 시각만 보관하며 terminal record는 최대 한 번 생성한다."""

    __slots__ = ("_recorder", "_operation", "_ids", "_started_at", "_finished")

    def __init__(
        self,
        recorder: AuditRecorder,
        operation: AuditOperation,
        ids: tuple[str, str],
        started_at: float | None,
    ) -> None:
        self._recorder = recorder
        self._operation = operation if type(operation) is AuditOperation else None
        self._ids = ids
        self._started_at = started_at
        self._finished = False

    def set_operation(self, operation: AuditOperation) -> None:
        """검증된 RPC 종류가 정해진 뒤에만 작업을 바꾸고 잘못된 값은 record를 폐기한다."""

        if not self._finished:
            self._operation = operation if type(operation) is AuditOperation else None

    @contextmanager
    def context(self) -> Iterator[None]:
        """SDK 장수 task에서도 현재 HTTP 요청의 안전한 ID만 일시 복원한다."""

        with self._recorder.context(request_id=self._ids[0], correlation_id=self._ids[1]):
            yield

    def finish(
        self,
        status: AuditStatus,
        *,
        error_class: AuditError | None = None,
    ) -> None:
        """enum·측정값을 최종 검사한 여섯 필드만 기록하며 재호출·장애 시 재시도하지 않는다."""

        if self._finished:
            return
        self._finished = True
        if (
            self._operation is None
            or type(status) is not AuditStatus
            or error_class is not None and type(error_class) is not AuditError
            or self._started_at is None
        ):
            return
        ended_at = _read_clock(self._recorder._clock)
        if ended_at is None:
            return
        duration_ms = (ended_at - self._started_at) * 1000.0
        if not math.isfinite(duration_ms) or duration_ms < 0:
            return
        self._recorder._emit({
            "request_id": self._ids[0],
            "correlation_id": self._ids[1],
            "operation": self._operation.value,
            "status": status.value,
            "duration_ms": duration_ms,
            "error_class": error_class.value if error_class is not None else None,
        })


# Python logger의 filter는 child logger에 상속되지 않는다. 고정된 MCP SDK 1.29.1과
# 설치된 httpcore의 실제 logger 이름마다 설치하며, 의존성 갱신 시 목록을 재검증한다.
# application record는 이 경로를 거치지 않고 AuditSink로만 전달한다.
DEPENDENCY_LOGGER_NAMES = (
    "mcp.server.lowlevel.server",
    "mcp.server.lowlevel.experimental",
    "mcp.server.streamable_http",
    "mcp.server.streamable_http_manager",
    "mcp.server.session",
    "mcp.server.transport_security",
    "mcp.server.experimental.task_result_handler",
    "mcp.shared.session",
    "mcp.shared.tool_name_validation",
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
    "uvicorn.error",
    "uvicorn.asgi",
)


class _DiscardDependencyRecord(logging.Filter):
    """의존성 payload·header·traceback을 formatter 호출 전에 읽지 않고 폐기한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        return False


_DEPENDENCY_FILTER = _DiscardDependencyRecord()
_DEPENDENCY_FILTER_LOCK = threading.Lock()
_dependency_filter_users = 0


@contextmanager
def isolate_dependency_logs() -> Iterator[None]:
    """동시 runtime 수명 동안 원문 logger를 차단하고 마지막 종료에서만 복원한다.

    SDK나 handler를 교체하지 않고 logging의 공개 filter API만 사용한다. process 전역
    logger를 공유하므로 다른 app의 lifespan이 살아 있는 동안 filter를 제거하지 않는다.
    원문 record를 보관하거나 대체 formatter·sink로 전달하지 않는다.
    """

    global _dependency_filter_users
    with _DEPENDENCY_FILTER_LOCK:
        if _dependency_filter_users == 0:
            for name in DEPENDENCY_LOGGER_NAMES:
                logging.getLogger(name).addFilter(_DEPENDENCY_FILTER)
        _dependency_filter_users += 1
    try:
        yield
    finally:
        with _DEPENDENCY_FILTER_LOCK:
            _dependency_filter_users -= 1
            if _dependency_filter_users == 0:
                for name in DEPENDENCY_LOGGER_NAMES:
                    logging.getLogger(name).removeFilter(_DEPENDENCY_FILTER)
