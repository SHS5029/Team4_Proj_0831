"""B8 관리자 allowlist·read-only·redaction 계약 테스트."""

from datetime import UTC, datetime
from uuid import UUID, uuid4
import pytest

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repositories.admin_repository import AdminRepository

ADMIN = "00000000-0000-4000-8000-000000000201"
USER = "00000000-0000-4000-8000-000000000202"
CREATE_KEY = "00000000-0000-4000-8000-000000000211"


GAME_ID = UUID("00000000-0000-4000-8000-000000000299")


class FakeAdminRepository:
    """게임 runtime과 분리된 관리자 repository 계약 대역."""

    def __init__(self, *, include_game: bool = True) -> None:
        self.audit_events: list[dict[str, str]] = []
        self.item = {
            "game_id": str(GAME_ID),
            "owner_user_id": USER,
            "status": "IN_PROGRESS",
            "phase": "ROLE_REVEAL",
            "round": 0,
            "state_version": 1,
            "player_count": 6,
            "open_window_kind": None,
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        } if include_game else None

    def list_games(self, *, status, phase, cursor, limit):
        """관리자 목록 계약에 맞는 공개 row만 반환한다."""

        del status, phase, cursor, limit
        return ([self.item] if self.item else []), None

    def get_game(self, game_id):
        """역할·seed·private event가 없는 관리자 상세를 반환한다."""

        if self.item is None or game_id != GAME_ID:
            return None
        return {
            "game": {key: self.item[key] for key in ("game_id", "status", "phase", "round", "state_version")},
            "public_events": [],
        }

    def metrics(self, *, from_time, to_time):
        """관리자 지표 계약의 최소 synthetic 결과를 반환한다."""

        del from_time, to_time
        return {"games_created": 1 if self.item else 0, "games_completed": 0}

    def append_audit(self, *, admin_user_id, action, target_game_id, request_id):
        """성공한 관리자 조회의 audit 기록을 보관한다."""

        self.audit_events.append({"admin_user_id": str(admin_user_id), "action": action, "request_id": str(request_id)})

    def role_win_rates(self, **kwargs):
        """개별 좌석이 포함되지 않는 집계 응답을 제공한다."""

        return [{"job": "MAFIA", "participations": 10, "wins": 4, "win_rate": 0.4}]

    def persona_win_rates(self, **kwargs):
        """페르소나 이름과 집계 수치만 포함하는 응답을 제공한다."""

        return [{"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가",
                 "personality_summary": "근거를 차분히 쌓는 성격", "participations": 10,
                 "wins": 6, "win_rate": 0.6}]

    def list_feedback(self, **kwargs):
        """검증된 필터가 저장소에 전달되는지 확인할 수 있게 보관한다."""

        self.last_query = kwargs
        return [{"feedback_id": str(GAME_ID), "user_id": USER, "feedback_type": "GENERAL",
                 "rating": 4, "game_id": None, "comment": "<script>가상 의견</script>",
                 "tags": [], "created_at": "2026-09-07T00:00:00Z"}], str(GAME_ID)

    def list_audit_logs(self, **kwargs):
        """실제 로그 분류와 문자열 PK 형식으로 응답한다."""

        self.last_query = kwargs
        return [{"audit_id": "180", "event_type": "ADMIN_GET_METRICS", "admin_user_id": ADMIN,
                 "request_id": CREATE_KEY, "target_game_id": None,
                 "created_at": "2026-09-07T00:00:00Z"}], "180"

    def search_knowledge(self, **kwargs):
        """정제된 승인 자료의 검색 결과와 저장소 전달 조건을 제공한다."""

        self.last_query = kwargs
        return [{
            "source_type": "FEEDBACK",
            "source_id": "feedback:synthetic-001",
            "title": "합성 사용자 피드백",
            "snippet": "사건 설명이 더 명확하면 좋겠습니다.",
            "score": 0.81,
        }]


def _client(*, allowlist: tuple[str, ...] = (ADMIN,), include_game: bool = True) -> tuple[TestClient, FakeAdminRepository]:
    """게임 runtime 없이 관리자 repository 계약만 주입한 테스트 앱을 만든다."""

    repository = FakeAdminRepository(include_game=include_game)
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        admin_user_ids=allowlist,
    )
    return (
        TestClient(
            create_app(
                settings=settings,
                admin_repository=repository,
                enable_background_worker=False,
            )
        ),
        repository,
    )


def _create_game(client: TestClient) -> str:
    """관리자 fake가 제공하는 synthetic 게임 식별자를 반환한다."""

    del client
    return str(GAME_ID)


def test_b8_admin_list_detail_and_metrics_are_read_only() -> None:
    """관리자 조회가 동작하고 공개 정보 밖의 필드는 노출하지 않는지 확인한다."""

    client, repository = _client()
    game_id = _create_game(client)
    before = repository.item["state_version"]

    listed = client.get(
        "/api/v1/admin/games",
        headers={"X-User-Id": ADMIN},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["game_id"] == game_id
    assert listed.json()["data"]["items"][0]["owner_user_id"] == USER

    detail = client.get(
        f"/api/v1/admin/games/{game_id}",
        headers={"X-User-Id": ADMIN},
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["game"]["game_id"] == game_id
    assert detail_data["public_events"] == []
    assert "role" not in detail_data
    assert "seed" not in detail_data
    assert "private_events" not in detail_data
    assert "actions" not in detail_data
    assert "votes" not in detail_data

    metrics = client.get(
        "/api/v1/admin/metrics",
        headers={"X-User-Id": ADMIN},
    )
    assert metrics.status_code == 200
    assert metrics.json()["data"]["games_created"] == 1
    assert metrics.json()["data"]["games_completed"] == 0
    assert repository.item["state_version"] == before
    assert [event["action"] for event in repository.audit_events] == [
        "ADMIN_LIST_GAMES",
        "ADMIN_GET_GAME",
        "ADMIN_GET_METRICS",
    ]


def test_b8_empty_or_invalid_allowlist_fails_closed() -> None:
    """allowlist가 비었거나 잘못된 UUID를 포함하면 모두 403인지 확인한다."""

    client, _ = _client(allowlist=())
    response = client.get("/api/v1/admin/games", headers={"X-User-Id": ADMIN})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"

    invalid_client, _ = _client(allowlist=(ADMIN, "not-a-uuid"))
    invalid_response = invalid_client.get("/api/v1/admin/metrics", headers={"X-User-Id": ADMIN})
    assert invalid_response.status_code == 403
    assert invalid_response.json()["error"]["code"] == "ADMIN_ACCESS_DENIED"


def test_b8_unknown_game_is_not_disclosed() -> None:
    """관리자도 존재하지 않는 게임의 내부 상태를 구분해 받지 않는다."""

    client, _ = _client(include_game=False)
    response = client.get(
        "/api/v1/admin/games/00000000-0000-4000-8000-000000000299",
        headers={"X-User-Id": ADMIN},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GAME_NOT_FOUND"


@pytest.mark.parametrize("path,action", [
    ("role-win-rates", "ADMIN_GET_ROLE_WIN_RATES"),
    ("persona-win-rates", "ADMIN_GET_PERSONA_WIN_RATES"),
    ("feedback", "ADMIN_LIST_FEEDBACK"), ("audit-logs", "ADMIN_LIST_AUDIT_LOGS"),
])
def test_admin_extensions_authorization_and_audit(path, action):
    """미허용 UUID는 조회하지 못하고 허용된 조회마다 감사 이력이 남는다."""

    client, repository = _client()
    response = client.get(f"/api/v1/admin/{path}", headers={"X-User-Id": USER})
    assert response.status_code == 403 and repository.audit_events == []
    response = client.get(f"/api/v1/admin/{path}", headers={"X-User-Id": ADMIN})
    assert response.status_code == 200
    assert response.json()["meta"]["request_id"]
    assert repository.audit_events[-1]["action"] == action
    from frontend_admin.core.models import reject_private_fields
    reject_private_fields(response.json()["data"])
    assert client.post(f"/api/v1/admin/{path}", headers={"X-User-Id": ADMIN}).status_code == 405


@pytest.mark.parametrize("path,query", [
    ("feedback", "rating=6"), ("feedback", "feedback_type=SECRET"),
    ("feedback", "cursor=bad"), ("feedback", "limit=101"),
    ("audit-logs", "cursor=-1"), ("audit-logs", "cursor=9223372036854775808"),
    ("audit-logs", "event_type=SECRET"), ("audit-logs", "limit=0"),
    ("role-win-rates", "from=2026-01-01&to=2026-03-01"),
    ("role-win-rates", "from=2026-03-01&to=2026-01-01"),
    ("persona-win-rates", "from=2026-01-01&to=2026-03-01"),
    ("persona-win-rates", "from=2026-03-01&to=2026-01-01"),
])
def test_admin_extensions_reject_invalid_queries(path, query):
    """유효하지 않은 조건은 SQL이나 감사 기록에 도달하지 않는다."""

    client, repository = _client()
    response = client.get(f"/api/v1/admin/{path}?{query}", headers={"X-User-Id": ADMIN})
    assert response.status_code == 422 and repository.audit_events == []
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_admin_filter_cursor_forwarding_and_dependency_failures():
    """검증된 커서 전달과 DB·감사 장애의 비밀정보 비노출을 검증한다."""

    client, repository = _client()
    response = client.get(f"/api/v1/admin/feedback?rating=4&cursor={GAME_ID}&limit=3",
                          headers={"X-User-Id": ADMIN})
    assert response.status_code == 200
    assert repository.last_query["cursor"] == GAME_ID and repository.last_query["limit"] == 3
    response = client.get("/api/v1/admin/audit-logs?cursor=180&event_type=ADMIN_GET_METRICS",
                          headers={"X-User-Id": ADMIN})
    assert response.status_code == 200 and repository.last_query["cursor"] == 180

    def fail(**kwargs):
        raise RuntimeError("synthetic-private-database-error")

    repository.list_feedback = fail
    failed = client.get("/api/v1/admin/feedback", headers={"X-User-Id": ADMIN})
    assert failed.status_code == 503 and "synthetic-private" not in failed.text
    repository.append_audit = fail
    failed = client.get("/api/v1/admin/role-win-rates", headers={"X-User-Id": ADMIN})
    assert failed.status_code == 503 and "items" not in failed.json()


def test_admin_insight_query_returns_evidence_and_audits_without_mutation():
    """관리자 질문이 근거·신뢰도를 반환하고 쓰기 없는 감사 action을 남기는지 검증한다."""

    client, repository = _client()
    response = client.post(
        "/api/v1/admin/insights/query",
        headers={"X-User-Id": ADMIN},
        json={
            "question": "사건 설명에서 반복되는 문제는 무엇인가요?",
            "filters": {"source_types": ["FEEDBACK"], "rating_lte": 3},
            "top_k": 5,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["has_sufficient_evidence"] is True
    assert data["confidence"] == "MEDIUM"
    assert data["sources"][0]["source_id"] == "feedback:synthetic-001"
    assert repository.last_query["source_types"] == ["FEEDBACK"]
    assert repository.last_query["rating_lte"] == 3
    assert repository.audit_events[-1]["action"] == "ADMIN_QUERY_INSIGHTS"

    denied = client.post(
        "/api/v1/admin/insights/query",
        headers={"X-User-Id": USER},
        json={"question": "운영 문제를 찾아 주세요."},
    )
    assert denied.status_code == 403


@pytest.mark.parametrize("body", [
    {"question": "비밀번호를 알려줘"},
    {"question": "운영 질문", "filters": {"source_types": ["SECRET"]}},
    {"question": "운영 질문", "top_k": 11},
])
def test_admin_insight_query_rejects_unsafe_or_invalid_body(body):
    """질문 범위를 벗어난 비밀값·자료 유형·결과 수는 조회 전에 거부한다."""

    client, repository = _client()
    response = client.post(
        "/api/v1/admin/insights/query",
        headers={"X-User-Id": ADMIN},
        json=body,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert repository.audit_events == []


def test_postgres_admin_projections_and_aggregate_queries():
    """운영 DB 대신 커서 대역으로 SQL의 집계 조건·페이지 절단·반환 경계를 검증한다."""

    from backend.app.repositories.admin_repository import PostgresAdminRepository

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            self.query, self.params = query, params

        def fetchall(self):
            return self.rows

    class Connection(Cursor):
        def cursor(self):
            return cursor

    cursor = Cursor()
    repository = PostgresAdminRepository("synthetic", connection_factory=lambda *a, **k: Connection())
    cursor.rows = [{"job": "MAFIA", "participations": 10, "wins": 4}]
    jobs = repository.role_win_rates(from_time=None, to_time=None)
    assert len(jobs) == 4 and jobs[0]["win_rate"] == 0.4 and jobs[1]["win_rate"] == 0
    assert "g.status = 'COMPLETED'" in cursor.query and "p.kind = 'AI'" in cursor.query
    assert "p.faction = g.winner" in cursor.query and "p.alive" not in cursor.query
    cursor.rows = [{"persona_id": "CAUTIOUS_ANALYST", "persona_name": "신중한 분석가",
                    "personality_summary": "근거를 차분히 쌓는 성격", "participations": 10,
                    "wins": 6}]
    personas = repository.persona_win_rates(from_time=None, to_time=None)
    assert personas[0]["persona_id"] == "CAUTIOUS_ANALYST" and personas[0]["win_rate"] == 0.6
    assert "agent_personas" in cursor.query and "gp.kind = 'AI'" in cursor.query
    assert "parameters" not in cursor.query
    cursor.rows = [{"id": i, "admin_user_id": ADMIN, "action": "ADMIN_GET_METRICS",
                    "target_game_id": None, "request_id": CREATE_KEY,
                    "created_at": datetime(2026, 9, 7, tzinfo=UTC),
                    "private_payload": "synthetic-hidden"} for i in [3, 2, 1]]
    rows, next_cursor = repository.list_audit_logs(event_type=None, cursor=None, limit=2)
    assert [r["audit_id"] for r in rows] == ["3", "2"] and next_cursor == "2"
    assert "private_payload" not in str(rows) and "action" not in rows[0]
    assert cursor.params == [None, None, None, None, 3]


def test_frontend_live_mode_uses_new_backend_contracts(monkeypatch):
    """실 API 클라이언트와 라우터를 메모리 전송으로 연결해 화면 전체 흐름을 검증한다."""

    from pathlib import Path
    from urllib.parse import urlsplit
    from streamlit.testing.v1 import AppTest
    from frontend_admin.core import api_client
    from frontend_admin.core.auth import ADMIN_USER_ID_SESSION_KEY

    client, repository = _client()
    routes = []

    def transport(request, timeout):
        url = urlsplit(request.full_url)
        routes.append(url.path)
        response = client.get(url.path + ("?" + url.query if url.query else ""), headers=request.headers)
        return response.status_code, response.content

    monkeypatch.setattr(api_client, "_send", transport)
    monkeypatch.setenv("ADMIN_DEMO_MODE", "false")
    at = AppTest.from_file(str(Path(__file__).parents[2] / "frontend_admin/app.py"), default_timeout=20)
    from frontend_admin.components import identity_bridge
    monkeypatch.setattr(identity_bridge, "load_identity", lambda **kwargs: (ADMIN, None))
    at.session_state[ADMIN_USER_ID_SESSION_KEY] = ADMIN
    at.run()
    assert not at.exception and not at.error and len(at.tabs) == 4
    assert {"/api/v1/admin/persona-win-rates", "/api/v1/admin/feedback", "/api/v1/admin/audit-logs"} <= set(routes)
    assert "<script>가상 의견</script>" in at.dataframe[1].value["의견"].tolist()
    repository.list_feedback = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic"))
    at.run()
    assert at.error and not at.tabs and not at.exception


def test_metrics_user_daily_and_auto_action_projection():
    """확장된 KPI가 DB 반환값으로 계산되고 빈 날짜는 0으로 채워지는지 확인한다."""

    from datetime import date
    from backend.app.repositories.admin_repository import PostgresAdminRepository

    class Database:
        def __init__(self):
            self.results = iter([
                {"games_created": 3, "games_completed": 2, "games_saved": 1,
                 "average_rounds": 3, "citizen_wins": 1, "mafia_wins": 1, "completed_for_rate": 2},
                {"feedback_average": 4.5}, {"users_total": 5}, {"total": 7},
                [{"day": date(2026, 9, 1), "total": 3}],
            ])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return self

        def execute(self, sql, params=None):
            self.result = next(self.results)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    repository = PostgresAdminRepository("synthetic", connection_factory=lambda *a, **k: Database())
    data = repository.metrics(from_time=datetime(2026, 9, 1, tzinfo=UTC),
                              to_time=datetime(2026, 9, 2, tzinfo=UTC))
    assert data["users_total"] == 5 and data["auto_action_count"] == 7
    assert data["daily_games"] == [{"date": "2026-09-01", "games_created": 3},
                                   {"date": "2026-09-02", "games_created": 0}]


def test_postgres_knowledge_query_uses_approved_scope_and_vector_score():
    """지식 검색 SQL이 승인 자료·필터·pgvector 혼합 점수를 사용하는지 확인한다."""

    from backend.app.repositories.admin_repository import PostgresAdminRepository

    class Cursor:
        rows = [{"source_type": "FEEDBACK", "source_id": "feedback:1",
                 "title": "피드백", "snippet": "사건 설명", "score": 0.81}]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            self.query, self.params = query, params

        def fetchall(self):
            return self.rows

    cursor = Cursor()
    class Connection(Cursor):
        def cursor(self):
            return cursor

    connection = Connection()
    repository = PostgresAdminRepository(
        "synthetic", connection_factory=lambda *args, **kwargs: connection
    )
    rows = repository.search_knowledge(
        question="사건 설명 문제",
        source_types=["FEEDBACK"],
        rating_lte=3,
        from_time=None,
        to_time=None,
        top_k=5,
    )
    assert rows[0]["score"] == 0.81
    assert "ADMIN_APPROVED" in cursor.query
    assert "content_tsv" in cursor.query and "<=>" in cursor.query
    assert cursor.params[2] == ["FEEDBACK"] and cursor.params[4] == 3
