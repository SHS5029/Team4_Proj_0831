"""실제 DB·Provider 없이 저장소의 공개 입력과 fencing SQL 경계를 검증한다."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.repositories.speech_analysis_repository import PostgresSpeechAnalysisRepository


class ScriptedTransactions:
    """SQL별 합성 응답과 transaction 종료 여부를 추적한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.statements = []
        self.committed = 0
        self.rolled_back = 0
        self.active = False

    @contextmanager
    def transaction(self):
        self.active = True
        try:
            yield self
            self.committed += 1
        except Exception:
            self.rolled_back += 1
            raise
        finally:
            self.active = False

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def execute(self, sql, params=()):
        assert sql.count('%s') == len(params)
        self.statements.append((' '.join(sql.split()), params))
        self.result = self.responses.pop(0)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


def test_discover_uses_public_ai_original_window_and_idempotent_insert():
    """다음 phase가 먼저 기록되는 경계에서도 당시 SPEECH window로 소속을 복원한다."""
    tx = ScriptedTransactions(None, None, None, [{'id': uuid4()}])
    repo = PostgresSpeechAnalysisRepository(tx)
    assert repo.discover(analysis_version='v1', embedding_model='model', dimensions=2, claims_model='claims') == 1
    sql, params = tx.statements[-1]
    assert "e.audience = 'PUBLIC'" in sql and "p.kind IN ('HUMAN', 'AI')" in sql
    assert "e.event_type = 'PLAYER_SPOKE'" in sql
    assert "e.operation_type = 'APPEND_PUBLIC_EVENT'" in sql
    assert "e.schema_version = 1" in sql and "e.audience_player_id IS NULL" in sql
    assert "se.sequence < e.sequence" in sql
    assert "se.operation_type = 'SET_ACTION_WINDOW'" in sql
    assert "w.game_id = e.game_id" in sql and "w.window_kind = 'SPEECH'" in sql
    assert "ON CONFLICT (event_id, analysis_version) DO NOTHING" in sql
    assert "g.status IN ('IN_PROGRESS','SAVED')" in sql
    assert (params[4], params[7]) == (None, None)
    assert tx.committed == 1 and not tx.active


def test_explicit_game_id_enables_backfill_and_duplicates_return_zero():
    tx = ScriptedTransactions(None, None, None, [])
    game = uuid4()
    assert PostgresSpeechAnalysisRepository(tx).discover(
        analysis_version='v1', embedding_model='m', dimensions=2, claims_model='c', game_id=game) == 0
    assert (tx.statements[-1][1][4], tx.statements[-1][1][7]) == (game, game)


def test_reused_version_with_different_model_is_rejected():
    tx = ScriptedTransactions(None, None, {'exists': 1})
    with pytest.raises(ValueError):
        PostgresSpeechAnalysisRepository(tx).discover(
            analysis_version='v1', embedding_model='m', dimensions=2, claims_model='c')
    assert len(tx.statements) == 3 and tx.rolled_back == 1
    assert 'pg_advisory_xact_lock' in tx.statements[0][0]


def test_claim_returns_only_public_input_and_releases_transaction():
    job, token, game, event, player = [uuid4() for _ in range(5)]
    public = {'player_id': player, 'display_name': '합성 인물', 'seat': 1, 'kind': 'AI'}
    tx = ScriptedTransactions(None, {'job_id': job, 'lease_token': token, 'stage': 'CLAIMS',
                               'game_id': game, 'event_id': event}, {'message': '합성 발언'}, [public])
    result = PostgresSpeechAnalysisRepository(tx).claim_next(analysis_version='v1')
    assert result == {'job_id': job, 'lease_token': token, 'stage': 'CLAIMS',
                      'message': '합성 발언', 'players': [public]}
    recovery = tx.statements[0][0]
    sql = tx.statements[1][0]
    assert 'FOR UPDATE SKIP LOCKED' in sql
    assert 'lease_expires_at <= clock_timestamp()' in recovery
    assert 'AND lease_token IS NULL' in sql
    assert "OR (claims_status <> 'READY'" in sql
    assert 'claims_attempts < %s' in sql and 'embedding_attempts < %s' in sql
    assert "role" not in tx.statements[-1][0] and "faction" not in tx.statements[-1][0]
    assert not tx.active and tx.committed == 1


def test_no_eligible_job_returns_none():
    tx = ScriptedTransactions(None, None)
    assert PostgresSpeechAnalysisRepository(tx).claim_next(analysis_version='v1') is None
    assert len(tx.statements) == 2


@pytest.mark.parametrize('vector', [[], [1], [0, 0], [float('nan'), 1], [float('inf'), 1],
                                     [float('-inf'), 1], [True, 1], ['1', 2], [[1], 2], [10**999, 1]])
def test_invalid_embedding_is_rejected_before_update(vector):
    tx = ScriptedTransactions({'dimensions': 2, 'game_id': uuid4(), 'message': '합성'})
    with pytest.raises(ValueError):
        PostgresSpeechAnalysisRepository(tx).complete_embedding(job_id=uuid4(), lease_token=uuid4(), embedding=vector)
    assert len(tx.statements) == 1 and tx.rolled_back == 1


def test_embedding_completion_rechecks_expiry_after_validation():
    tx = ScriptedTransactions({'dimensions': 2}, None)
    assert not PostgresSpeechAnalysisRepository(tx).complete_embedding(
        job_id=uuid4(), lease_token=uuid4(), embedding=[0.5, -0.5])
    sql = tx.statements[-1][0]
    assert "lease_stage = 'EMBEDDING'" in sql and 'lease_expires_at > clock_timestamp()' in sql
    assert 'lease_token = %s' in sql


@pytest.mark.parametrize('method,args', [('complete_embedding', {'embedding': [1, 2]}),
                                       ('complete_claims', {'claims': []})])
def test_stale_token_is_rejected_without_result_write(method, args):
    tx = ScriptedTransactions(None)
    assert not getattr(PostgresSpeechAnalysisRepository(tx), method)(job_id=uuid4(), lease_token=uuid4(), **args)
    assert len(tx.statements) == 1
    assert 'lease_token = %s' in tx.statements[0][0]


def claim(**changes):
    item = {'target_player_id': None, 'stance': 'QUESTION', 'proposition': '합성 질문',
            'evidence_start': 0, 'evidence_end': 2, 'quote': '가😀'}
    return item | changes


@pytest.mark.parametrize('changes', [ {'target_player_id': str(uuid4())}, {'stance': 'TRUTH'},
    {'evidence_start': True}, {'evidence_start': -1}, {'evidence_end': 99},
    {'quote': '틀린 원문'}, {'proposition': ' '}, {'private_reasoning': '금지'}, {'stance': []}])
def test_claim_validation_rejects_wrong_game_offsets_and_extra_fields(changes):
    with pytest.raises(ValueError):
        PostgresSpeechAnalysisRepository._claims([claim(**changes)], '가😀나다', set())


def test_claims_nullable_target_unicode_offsets_and_independent_completion():
    tx = ScriptedTransactions({'dimensions': 2, 'game_id': uuid4(), 'message': '가😀나다'}, [], {'id': uuid4()})
    assert PostgresSpeechAnalysisRepository(tx).complete_claims(
        job_id=uuid4(), lease_token=uuid4(), claims=[claim()])
    sql = tx.statements[-1][0]
    assert 'embedding_status' not in sql and 'embedding =' not in sql
    assert 'lease_expires_at > clock_timestamp()' in sql
    assert tx.statements[-1][1][0].obj == [claim()]


def test_claims_failure_preserves_embedding_and_uses_atomic_fencing():
    tx = ScriptedTransactions({'id': uuid4()})
    assert PostgresSpeechAnalysisRepository(tx).fail(job_id=uuid4(), lease_token=uuid4(),
                                                    stage='CLAIMS', failure_code='TIMEOUT')
    sql = tx.statements[0][0]
    assert "claims_status = 'FAILED'" in sql and 'claims_retry_at' in sql
    assert 'embedding' not in sql and 'lease_expires_at > clock_timestamp()' in sql
    assert 'lease_token = %s' in sql and 'lease_stage = %s' in sql


@pytest.mark.parametrize('code', ['external error text', '', 'TIMEOUT\nsecret', 'a'*65])
def test_error_details_cannot_be_saved_as_failure_code(code):
    tx = ScriptedTransactions()
    with pytest.raises(ValueError):
        PostgresSpeechAnalysisRepository(tx).fail(job_id=uuid4(), lease_token=uuid4(), stage='CLAIMS', failure_code=code)
    assert tx.statements == []


def test_migration_declares_composite_binding_and_no_pgvector_dependency():
    """실제 제약 동작은 M9 격리 DB에서 검증하고 여기서는 배포 계약의 누락을 감시한다."""
    sql = (Path(__file__).parents[1] / 'migrations/006_create_speech_analysis.sql').read_text()
    assert 'FOREIGN KEY (game_id, event_id, source_sequence)' in sql
    assert 'FOREIGN KEY (game_id, player_id)' in sql
    assert 'UNIQUE (event_id, analysis_version)' in sql
    assert 'embedding double precision[]' in sql
    assert 'CREATE EXTENSION' not in sql
    assert "p.game_id = NEW.game_id" in sql
    assert "source binding is immutable" in sql
    assert 'cardinality(NEW.embedding) <> NEW.dimensions' in sql


def test_final_speech_after_game_completion_is_discovered_for_tracked_game():
    """추적한 게임의 마지막 발언은 종료 상태 전환 이후에도 자동 탐색에 남는다."""
    tx = ScriptedTransactions(None, None, None, [{'id': uuid4()}])
    assert PostgresSpeechAnalysisRepository(tx).discover(
        analysis_version='v1', embedding_model='m', dimensions=2, claims_model='c') == 1
    sql, params = tx.statements[-1]
    assert "OR EXISTS (SELECT 1 FROM public.speech_analysis tracked" in sql
    assert 'tracked.game_id = g.id AND tracked.analysis_version = %s' in sql
    assert params[5] == 'v1'
    assert params[4] is None and params[7] is None


class LeaseTransactions(ScriptedTransactions):
    """합성 시계를 가진 단일 분석 행으로 재시작·늦은 응답 순서를 재현한다."""

    def __init__(self):
        super().__init__()
        self.now = 0
        self.job_id, self.game_id, self.event_id = uuid4(), uuid4(), uuid4()
        self.token = None
        self.expiry = 0
        self.stage = None
        self.status = {'EMBEDDING': 'PENDING', 'CLAIMS': 'PENDING'}
        self.attempts = {'EMBEDDING': 0, 'CLAIMS': 0}
        self.retry = {'EMBEDDING': 0, 'CLAIMS': 0}
        self.embedding = None
        self.claims = None
        self.exists = True
        self.version = 'v1'
        self.game_status, self.phase, self.day = 'IN_PROGRESS', 'DAY_DISCUSSION', 2
        self.window_status, self.window_kind, self.deadline = 'OPEN', 'SPEECH', 0
        self.failure = {'EMBEDDING': None, 'CLAIMS': None}

    def execute(self, sql, params=()):
        assert sql.count('%s') == len(params)
        sql = ' '.join(sql.split())
        self.statements.append((sql, params))
        self.result = None
        if not self.exists:
            return
        if 'WITH expired AS' in sql:
            if params[0] != self.version or self.token is None or self.expiry > self.now:
                return
            if self.status[self.stage] != 'READY' and self.attempts[self.stage] >= params[1]:
                self.status[self.stage] = 'FAILED'
                self.failure[self.stage] = 'LEASE_EXPIRED'
            self.token, self.stage = None, None
        elif 'WITH candidate AS' in sql:
            assert "g.status = 'IN_PROGRESS'" in sql
            assert 'current_window' not in sql
            assert 'g.phase' not in sql and 'g.day_number' not in sql
            assert 'FOR UPDATE SKIP LOCKED LIMIT 1' in sql
            assert '(%s::uuid IS NULL OR game_id = %s)' in sql
            if params[1] != self.version or (params[2] is not None and params[2] != self.game_id):
                return
            if self.game_status != 'IN_PROGRESS':
                return
            if self.token is not None and self.expiry > self.now:
                return
            eligible = [stage for stage in ('EMBEDDING', 'CLAIMS')
                        if self.status[stage] != 'READY' and self.attempts[stage] < params[0]
                        and self.retry[stage] <= self.now]
            if not eligible:
                return
            self.stage = eligible[0]
            self.attempts[self.stage] += 1
            self.token, self.expiry = params[-2], self.now + params[-1]
            self.result = {'job_id': self.job_id, 'game_id': self.game_id, 'event_id': self.event_id,
                           'lease_token': self.token, 'stage': self.stage}
        elif sql.startswith('SELECT NOT EXISTS'):
            assert 'a.game_id = %s AND a.analysis_version = %s' in sql
            assert "a.embedding_status = 'FAILED' AND a.embedding_attempts >= %s" in sql
            assert "a.claims_status = 'FAILED' AND a.claims_attempts >= %s" in sql
            assert 'a.lease_expires_at > clock_timestamp()' in sql
            terminal = all(self.status[stage] == 'READY' or
                           (self.status[stage] == 'FAILED' and self.attempts[stage] >= params[-1])
                           for stage in self.status)
            self.result = {'ready': terminal and not (self.token is not None and self.expiry > self.now)}
        elif sql.startswith("SELECT payload->>'message'"):
            self.result = {'message': '가😀나다'}
        elif sql.startswith('SELECT id AS player_id') or sql.startswith('SELECT id FROM public.game_players'):
            self.result = []
        elif sql.startswith('SELECT a.dimensions'):
            if (params[0], params[1], params[2]) == (self.job_id, self.token, self.stage) and self.expiry > self.now:
                self.result = {'dimensions': 2, 'game_id': self.game_id, 'message': '가😀나다'}
        elif sql.startswith('UPDATE public.speech_analysis'):
            failed = "_status = 'FAILED'" in sql
            stage = params[-1] if failed else ('EMBEDDING' if 'SET embedding' in sql else 'CLAIMS')
            job, token = (params[2], params[3]) if failed else (params[1], params[2])
            if (job, token, stage) != (self.job_id, self.token, self.stage) or self.expiry <= self.now:
                return
            if failed:
                self.status[stage] = 'FAILED'
                self.retry[stage] = self.now + params[1]
            else:
                self.status[stage] = 'READY'
                if stage == 'EMBEDDING':
                    self.embedding = params[0]
                else:
                    self.claims = params[0].obj
            self.token, self.stage = None, None
            self.result = {'id': self.job_id}
        else:
            raise AssertionError('예상하지 않은 합성 SQL입니다.')


def test_expired_lease_reclaim_rejects_old_success_and_failure():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    old = repo.claim_next(analysis_version='v1', lease_seconds=10)
    assert repo.claim_next(analysis_version='v1') is None
    tx.now = 10
    new = repo.claim_next(analysis_version='v1', lease_seconds=10)
    assert old['lease_token'] != new['lease_token']
    assert tx.attempts['EMBEDDING'] == 2
    assert not repo.complete_embedding(job_id=old['job_id'], lease_token=old['lease_token'], embedding=[1, 0])
    assert not repo.fail(job_id=old['job_id'], lease_token=old['lease_token'], stage='EMBEDDING', failure_code='TIMEOUT')
    assert repo.complete_embedding(job_id=new['job_id'], lease_token=new['lease_token'], embedding=[1, 0])
    assert tx.embedding == [1.0, 0.0]


def test_embedding_success_survives_claims_failure_and_retry_limit():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    embedding = repo.claim_next(analysis_version='v1', max_attempts=1)
    assert repo.complete_embedding(job_id=embedding['job_id'], lease_token=embedding['lease_token'], embedding=[1, 0])
    claims = repo.claim_next(analysis_version='v1', max_attempts=1)
    assert claims['stage'] == 'CLAIMS'
    assert repo.fail(job_id=claims['job_id'], lease_token=claims['lease_token'], stage='CLAIMS', failure_code='TIMEOUT', retry_seconds=0)
    assert repo.claim_next(analysis_version='v1', max_attempts=1) is None
    assert tx.embedding == [1.0, 0.0] and tx.status['EMBEDDING'] == 'READY'


def test_claims_runs_during_embedding_backoff_and_embedding_can_resume_later():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    embedding = repo.claim_next(analysis_version='v1')
    assert repo.fail(job_id=embedding['job_id'], lease_token=embedding['lease_token'], stage='EMBEDDING', failure_code='TIMEOUT')
    claims = repo.claim_next(analysis_version='v1')
    assert claims['stage'] == 'CLAIMS'
    assert repo.complete_claims(job_id=claims['job_id'], lease_token=claims['lease_token'], claims=[claim()])
    assert repo.claim_next(analysis_version='v1') is None
    tx.now = 30
    assert repo.claim_next(analysis_version='v1')['stage'] == 'EMBEDDING'


class DiscoveryTransactions(ScriptedTransactions):
    """버전 등록과 게임 종료 순서를 합성 데이터로 재현하며 SQL의 시간 경계도 검사한다."""

    def __init__(self):
        super().__init__()
        self.now = 10
        self.versions = {}
        self.games = {}
        self.speeches = []
        self.saved = set()

    def execute(self, sql, params=()):
        assert sql.count('%s') == len(params)
        sql = ' '.join(sql.split())
        self.statements.append((sql, params))
        self.result = None
        if 'pg_advisory_xact_lock' in sql:
            return
        if sql.startswith('INSERT INTO public.speech_analysis_versions'):
            assert 'ON CONFLICT (analysis_version) DO NOTHING' in sql
            self.versions.setdefault(params[0], (params[1:4], self.now))
        elif sql.startswith('SELECT 1 FROM public.speech_analysis_versions'):
            if self.versions[params[0]][0] != params[1:4]:
                self.result = {'exists': 1}
        elif sql.startswith('INSERT INTO public.speech_analysis ('):
            assert 'g.updated_at >= v.activated_at' in sql
            assert 'recent.game_id = g.id' in sql
            assert 'recent.created_at >= v.activated_at' in sql
            assert 'e.created_at >= v.activated_at' not in sql
            version, explicit, limit = params[0], params[4], params[-1]
            assert params[5:9] == (version, version, explicit, version)
            activation = self.versions[version][1]
            candidates = []
            for event, game, created in self.speeches:
                status, updated = self.games[game]
                eligible = (game == explicit if explicit is not None else (
                    status in ('IN_PROGRESS', 'SAVED') or updated >= activation
                    or any(g == game and v == version for _, g, v in self.saved)
                    or any(g == game and t >= activation for _, g, t in self.speeches)))
                if eligible and (event, game, version) not in self.saved:
                    candidates.append((created, event, game))
            selected = sorted(candidates)[:limit]
            self.saved.update((event, game, version) for _, event, game in selected)
            self.result = [{'id': event} for _, event, _ in selected]
        elif sql.startswith('WITH expired AS'):
            return
        elif sql.startswith('SELECT NOT EXISTS'):
            assert 'LIMIT' not in sql.split(') s ON true')[-1]
            assert "e.audience = 'PUBLIC'" in sql and "p.kind IN ('HUMAN', 'AI')" in sql
            assert "w.phase IN ('DAY_DISCUSSION', 'FINAL_DISCUSSION')" in sql
            game, version = params[:2]
            self.result = {'ready': all((event, game, version) in self.saved
                                       for event, source_game, _ in self.speeches if source_game == game)}
        else:
            raise AssertionError('예상하지 않은 버전 탐색 SQL입니다.')


def discover(repo, **changes):
    return repo.discover(**({'analysis_version': 'v1', 'embedding_model': 'm',
                            'dimensions': 2, 'claims_model': 'c'} | changes))


@pytest.mark.parametrize('status', ['COMPLETED', 'FAILED'])
def test_untracked_game_finishes_behind_backlog_and_its_old_speeches_are_found(status):
    tx = DiscoveryTransactions()
    tx.games = {'backlog': ('IN_PROGRESS', 0), 'race': ('IN_PROGRESS', 0),
                'historical': ('COMPLETED', 0)}
    tx.speeches = [(1, 'backlog', 1), (2, 'race', 2), (3, 'historical', 3)]
    repo = PostgresSpeechAnalysisRepository(tx)
    assert discover(repo, limit=1) == 1
    assert (2, 'race', 'v1') not in tx.saved
    tx.games['race'] = (status, 11)
    tx.now = 20
    assert discover(PostgresSpeechAnalysisRepository(tx)) == 1
    assert (2, 'race', 'v1') in tx.saved
    assert (3, 'historical', 'v1') not in tx.saved
    assert tx.versions['v1'][1] == 10
    assert discover(repo, game_id='historical') == 1


def test_empty_first_discovery_persists_activation_and_event_time_catches_finish():
    tx = DiscoveryTransactions()
    assert discover(PostgresSpeechAnalysisRepository(tx)) == 0
    tx.now = 30
    tx.games['race'] = ('COMPLETED', 1)
    tx.speeches = [(1, 'race', 2), (2, 'race', 11)]
    assert discover(PostgresSpeechAnalysisRepository(tx), limit=1) == 1
    assert (1, 'race', 'v1') in tx.saved
    assert discover(PostgresSpeechAnalysisRepository(tx)) == 1
    assert discover(PostgresSpeechAnalysisRepository(tx)) == 0
    assert tx.versions['v1'][1] == 10


@pytest.mark.parametrize('change', [{'embedding_model': 'other'}, {'dimensions': 3},
                                    {'claims_model': 'other'}])
def test_restart_rejects_model_mixing_even_without_analysis_rows(change):
    tx = DiscoveryTransactions()
    assert discover(PostgresSpeechAnalysisRepository(tx)) == 0
    tx.now = 100
    with pytest.raises(ValueError):
        discover(PostgresSpeechAnalysisRepository(tx), **change)
    assert tx.versions['v1'] == (('m', 2, 'c'), 10)
    assert tx.rolled_back == 1 and not tx.saved


def test_last_embedding_lease_crash_records_failure_and_claims_runs_independently():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    old = repo.claim_next(analysis_version='v1', max_attempts=1, lease_seconds=10)
    tx.now = 10
    new = repo.claim_next(analysis_version='v1', max_attempts=1)
    assert tx.status['EMBEDDING'] == 'FAILED'
    assert tx.failure['EMBEDDING'] == 'LEASE_EXPIRED'
    assert new['stage'] == 'CLAIMS'
    assert tx.status['CLAIMS'] == 'PENDING'
    assert not repo.complete_embedding(job_id=old['job_id'], lease_token=old['lease_token'], embedding=[1, 0])
    assert tx.token == new['lease_token']
    assert repo.complete_claims(job_id=new['job_id'], lease_token=new['lease_token'], claims=[])
    assert repo.claim_next(analysis_version='v1', max_attempts=1) is None
    assert tx.status['CLAIMS'] == 'READY'


def test_last_claims_save_lost_then_expiry_preserves_ready_embedding(monkeypatch):
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    first = repo.claim_next(analysis_version='v1', max_attempts=1)
    assert repo.complete_embedding(job_id=first['job_id'], lease_token=first['lease_token'], embedding=[1, 0])
    old = repo.claim_next(analysis_version='v1', max_attempts=1, lease_seconds=10)
    execute = tx.execute

    def fail_save(sql, params=()):
        if 'SET claims = ' in sql:
            raise RuntimeError('합성 DB 저장 실패')
        execute(sql, params)

    with monkeypatch.context() as patch:
        patch.setattr(tx, 'execute', fail_save)
        with pytest.raises(RuntimeError, match='합성 DB 저장 실패'):
            repo.complete_claims(job_id=old['job_id'], lease_token=old['lease_token'], claims=[])
    assert tx.rolled_back == 1 and tx.status['CLAIMS'] == 'PENDING'
    tx.now = 10
    assert repo.claim_next(analysis_version='v1', max_attempts=1) is None
    assert tx.failure['CLAIMS'] == 'LEASE_EXPIRED' and tx.status['CLAIMS'] == 'FAILED'
    assert tx.embedding == [1.0, 0.0] and tx.status['EMBEDDING'] == 'READY'
    assert not repo.complete_claims(job_id=old['job_id'], lease_token=old['lease_token'], claims=[])
    assert tx.token is None


def test_expiry_recovery_is_version_scoped_and_ready_results_are_not_rewritten():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    job = repo.claim_next(analysis_version='v1', max_attempts=1, lease_seconds=10)
    tx.now = 10
    assert repo.claim_next(analysis_version='v2', max_attempts=1) is None
    assert tx.token == job['lease_token'] and tx.status['EMBEDDING'] == 'PENDING'
    tx.status['EMBEDDING'], tx.embedding = 'READY', [1.0, 0.0]
    assert repo.claim_next(analysis_version='v1', max_attempts=1)['stage'] == 'CLAIMS'
    assert tx.failure['EMBEDDING'] is None and tx.embedding == [1.0, 0.0]
    recovery = next(sql for sql, _ in tx.statements if 'WITH expired AS' in sql)
    assert 'FOR UPDATE SKIP LOCKED LIMIT 100' in recovery
    assert 'a.lease_token = x.lease_token' in recovery
    assert 'a.lease_stage = x.lease_stage' in recovery
    assert 'a.analysis_version = %s' in recovery
    assert "AND a.embedding_status <> 'READY'" in recovery
    assert "AND a.claims_status <> 'READY'" in recovery


def test_migration_guards_forged_source_window_and_keeps_version_activation_on_rerun():
    """직접 SQL 위조의 실제 거부는 M9가 실행하며 여기서는 필수 trigger 조건을 고정한다."""
    sql = (Path(__file__).parents[1] / 'migrations/006_create_speech_analysis.sql').read_text()
    assert 'CREATE TABLE IF NOT EXISTS public.speech_analysis_versions' in sql
    assert 'activated_at timestamptz NOT NULL DEFAULT clock_timestamp()' in sql
    assert 'ON CONFLICT (analysis_version) DO NOTHING' in sql
    trigger = sql[sql.index('CREATE OR REPLACE FUNCTION'):]
    assert 'INTO source_message, source_phase, source_round' in trigger
    assert 'se.game_id = e.game_id AND se.sequence < e.sequence' in trigger
    assert "se.audience = 'PUBLIC' AND se.operation_type = 'SET_ACTION_WINDOW'" in trigger
    assert 'ORDER BY se.sequence DESC LIMIT 1' in trigger
    assert "w.id::text = s.payload->>'window_id' AND w.window_kind = 'SPEECH'" in trigger
    assert 'w.game_id = e.game_id' in trigger
    assert 'NEW.round IS DISTINCT FROM source_round' in trigger
    assert "NEW.discussion_segment IS DISTINCT FROM (source_phase || ':' || source_round::text)" in trigger
    assert 'length(source_message) NOT BETWEEN 1 AND 200' in trigger


@pytest.mark.parametrize('status', ['SAVED', 'COMPLETED', 'FAILED'])
@pytest.mark.parametrize('explicit_game', [False, True])
def test_non_running_game_cannot_claim_even_with_explicit_game(status, explicit_game):
    tx = LeaseTransactions()
    tx.game_status = status
    repo = PostgresSpeechAnalysisRepository(tx)
    assert repo.claim_next(analysis_version='v1', game_id=tx.game_id if explicit_game else None) is None
    assert tx.attempts == {'EMBEDDING': 0, 'CLAIMS': 0}


@pytest.mark.parametrize('changes', [
    {'day': 1, 'deadline': 100}, {'deadline': None}, {'deadline': 0},
    {'day': 3, 'deadline': 100}, {'phase': 'FINAL_DISCUSSION', 'deadline': 100},
    {'phase': 'NIGHT', 'window_kind': 'NIGHT'},
    {'phase': 'DAY_VOTE', 'window_kind': 'VOTE'},
    {'window_status': 'RESOLVING'}, {'window_status': 'CLOSED'},
])
def test_running_game_claims_confirmed_backlog_without_current_window_boundary(changes):
    tx = LeaseTransactions()
    for name, value in changes.items():
        setattr(tx, name, value)
    assert PostgresSpeechAnalysisRepository(tx).claim_next(analysis_version='v1', game_id=tx.game_id)


def prepare(repo, game_id, **changes):
    return repo.prepare_for_vote(**({'game_id': game_id, 'analysis_version': 'v1',
        'embedding_model': 'm', 'dimensions': 2, 'claims_model': 'c', 'max_attempts': 3} | changes))


@pytest.mark.parametrize('statuses,attempts,lease,ready', [
    (('READY', 'READY'), (1, 1), False, True),
    (('READY', 'FAILED'), (1, 3), False, True),
    (('FAILED', 'FAILED'), (3, 3), False, True),
    (('READY', 'PENDING'), (1, 0), False, False),
    (('FAILED', 'READY'), (2, 1), False, False),
    (('PENDING', 'READY'), (3, 1), False, False),
    (('READY', 'READY'), (1, 1), True, False),
    (('READY', 'FAILED'), (1, 3), True, False),
])
def test_prepare_waits_for_both_stages_retry_exhaustion_and_valid_lease(monkeypatch, statuses, attempts, lease, ready):
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    calls = []
    monkeypatch.setattr(repo, 'discover', lambda **kwargs: calls.append(kwargs))
    tx.status = dict(zip(tx.status, statuses))
    tx.attempts = dict(zip(tx.attempts, attempts))
    tx.retry = {'EMBEDDING': 100, 'CLAIMS': 100}
    if lease:
        tx.token, tx.stage, tx.expiry = uuid4(), 'CLAIMS', 10
    assert prepare(repo, tx.game_id) is ready
    assert calls[0]['game_id'] == tx.game_id and calls[0]['limit'] == 5000
    assert not tx.active
    assert not any('UPDATE public.games' in sql or 'WITH candidate AS' in sql for sql, _ in tx.statements)


def test_prepare_recovers_last_crashed_lease_and_keeps_ready_embedding(monkeypatch):
    tx = LeaseTransactions()
    tx.status = {'EMBEDDING': 'READY', 'CLAIMS': 'PENDING'}
    tx.attempts = {'EMBEDDING': 1, 'CLAIMS': 3}
    tx.embedding = [1, 0]
    tx.token, tx.stage, tx.expiry = uuid4(), 'CLAIMS', 10
    repo = PostgresSpeechAnalysisRepository(tx)
    monkeypatch.setattr(repo, 'discover', lambda **kwargs: 0)
    assert not prepare(repo, tx.game_id)
    tx.now = 10
    assert prepare(repo, tx.game_id)
    assert tx.failure['CLAIMS'] == 'LEASE_EXPIRED' and tx.embedding == [1, 0]


def test_prepare_does_not_treat_discovery_limit_as_complete_backlog():
    tx = DiscoveryTransactions()
    game = uuid4()
    tx.games = {game: ('IN_PROGRESS', 10)}
    tx.speeches = [(i, game, i) for i in range(5001)]
    repo = PostgresSpeechAnalysisRepository(tx)
    assert not prepare(repo, game)
    assert len(tx.saved) == 5000
    assert prepare(repo, game)
    assert len(tx.saved) == 5001 and tx.committed == 4
    assert not tx.active


def test_prepare_discovery_failure_propagates_without_claim_or_model(monkeypatch):
    tx = ScriptedTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    def unavailable(**kwargs):
        raise RuntimeError('합성 저장소 장애')
    monkeypatch.setattr(repo, 'discover', unavailable)
    with pytest.raises(RuntimeError, match='합성 저장소 장애'):
        prepare(repo, uuid4())
    assert tx.statements == []


def test_discovery_and_vote_preparation_share_exact_public_source_boundary():
    """등록과 완료 판정이 같은 원문 조건을 써야 사람 발언 누락이나 비공개 혼입이 없다."""
    tx = ScriptedTransactions(None, None, None, [], None, {'ready': True})
    assert prepare(PostgresSpeechAnalysisRepository(tx), uuid4())
    discovery_sql = next(sql for sql, _ in tx.statements
                         if sql.startswith('INSERT INTO public.speech_analysis ('))
    prepare_sql = tx.statements[-1][0]
    source_start = discovery_sql.index('FROM public.game_events e')
    source_end = discovery_sql.index(' AND ((%s::uuid IS NULL')
    source = discovery_sql[source_start:source_end]
    assert source in prepare_sql
    for boundary in (
        "p.kind IN ('HUMAN', 'AI')", "p.game_id = e.game_id",
        "p.id::text = e.payload->>'player_id'", "e.audience = 'PUBLIC'",
        "e.event_type = 'PLAYER_SPOKE'", "e.audience_player_id IS NULL",
        "e.operation_type = 'APPEND_PUBLIC_EVENT'", "e.schema_version = 1",
        "jsonb_typeof(e.payload->'message') = 'string'",
        "btrim(e.payload->>'message') <> ''",
        "length(e.payload->>'message') BETWEEN 1 AND 200",
        "w.phase IN ('DAY_DISCUSSION', 'FINAL_DISCUSSION')",
        "se.sequence < e.sequence", "se.operation_type = 'SET_ACTION_WINDOW'",
        "w.game_id = e.game_id", "w.window_kind = 'SPEECH'",
    ):
        assert boundary in source


def test_claim_missing_public_source_rolls_back_without_provider_input():
    job, token, game, event = [uuid4() for _ in range(4)]
    tx = ScriptedTransactions(None, {'job_id': job, 'lease_token': token, 'stage': 'EMBEDDING',
                                    'game_id': game, 'event_id': event}, None)
    with pytest.raises(ValueError, match='공개 발언 원본이 없습니다'):
        PostgresSpeechAnalysisRepository(tx).claim_next(analysis_version='v1')
    sql, params = tx.statements[-1]
    for boundary in ("game_id = %s", "id = %s", "audience = 'PUBLIC'",
                     "event_type = 'PLAYER_SPOKE'", "audience_player_id IS NULL",
                     "schema_version = 1", "operation_type = 'APPEND_PUBLIC_EVENT'"):
        assert boundary in sql
    assert params == (game, event)
    assert tx.rolled_back == 1 and tx.committed == 0 and not tx.active


@pytest.mark.parametrize('status', ['SAVED', 'COMPLETED', 'FAILED'])
@pytest.mark.parametrize('stage', ['EMBEDDING', 'CLAIMS'])
@pytest.mark.parametrize('succeed', [False, True])
def test_inflight_result_can_settle_after_game_stops_without_new_claim(status, stage, succeed):
    """중단 직전 지불한 호출의 유효 결과는 보존하되 다음 단계 호출을 새로 만들지 않는다."""
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    if stage == 'CLAIMS':
        tx.status['EMBEDDING'], tx.embedding = 'READY', [1.0, 0.0]
    job = repo.claim_next(analysis_version='v1')
    tx.game_status = status
    if succeed:
        if stage == 'EMBEDDING':
            assert repo.complete_embedding(job_id=job['job_id'], lease_token=job['lease_token'], embedding=[1, 0])
        else:
            assert repo.complete_claims(job_id=job['job_id'], lease_token=job['lease_token'], claims=[claim()])
    else:
        assert repo.fail(job_id=job['job_id'], lease_token=job['lease_token'],
                         stage=stage, failure_code='TIMEOUT', retry_seconds=0)
    assert tx.status[stage] == ('READY' if succeed else 'FAILED')
    assert repo.claim_next(analysis_version='v1', game_id=tx.game_id) is None
    assert tx.attempts[stage] == 1
    assert not any('UPDATE public.games' in sql or 'INSERT INTO public.game_events' in sql
                   for sql, _ in tx.statements)


def test_saved_game_resumes_pending_stage_without_repeating_ready_embedding():
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    embedding = repo.claim_next(analysis_version='v1')
    assert repo.complete_embedding(job_id=embedding['job_id'], lease_token=embedding['lease_token'], embedding=[1, 0])
    old = repo.claim_next(analysis_version='v1', lease_seconds=10)
    tx.game_status, tx.window_status = 'SAVED', 'PAUSED'
    tx.now = 10
    assert repo.claim_next(analysis_version='v1') is None
    assert tx.status == {'EMBEDDING': 'READY', 'CLAIMS': 'PENDING'}
    assert tx.attempts == {'EMBEDDING': 1, 'CLAIMS': 1}
    tx.game_status, tx.window_status, tx.deadline = 'IN_PROGRESS', 'OPEN', 100
    restarted = PostgresSpeechAnalysisRepository(tx)
    new = restarted.claim_next(analysis_version='v1')
    assert new['stage'] == 'CLAIMS' and new['lease_token'] != old['lease_token']
    assert not restarted.complete_claims(job_id=old['job_id'], lease_token=old['lease_token'], claims=[])
    assert restarted.complete_claims(job_id=new['job_id'], lease_token=new['lease_token'], claims=[claim()])
    assert restarted.claim_next(analysis_version='v1') is None
    assert tx.embedding == [1.0, 0.0] and tx.claims == [claim()]
    assert tx.attempts == {'EMBEDDING': 1, 'CLAIMS': 2}


def test_two_workers_share_one_lease_and_ready_results_are_not_reclaimed():
    """DB 동시 잠금 자체는 통합 담당자가 검증하고 여기서는 교차 worker 재호출을 재현한다."""
    tx = LeaseTransactions()
    first, second = PostgresSpeechAnalysisRepository(tx), PostgresSpeechAnalysisRepository(tx)
    embedding = first.claim_next(analysis_version='v1')
    assert second.claim_next(analysis_version='v1') is None
    assert first.complete_embedding(job_id=embedding['job_id'], lease_token=embedding['lease_token'], embedding=[1, 0])
    claims = second.claim_next(analysis_version='v1')
    assert claims['stage'] == 'CLAIMS' and first.claim_next(analysis_version='v1') is None
    assert second.complete_claims(job_id=claims['job_id'], lease_token=claims['lease_token'], claims=[])
    assert first.claim_next(analysis_version='v1') is None
    assert second.claim_next(analysis_version='v1') is None
    assert tx.attempts == {'EMBEDDING': 1, 'CLAIMS': 1}


@pytest.mark.parametrize('stage', ['EMBEDDING', 'CLAIMS'])
def test_deleted_source_rejects_late_success_failure_and_new_claim(stage):
    """FK cascade 뒤에는 유효했던 token으로도 결과 행을 다시 만들 수 없다."""
    tx = LeaseTransactions()
    repo = PostgresSpeechAnalysisRepository(tx)
    if stage == 'CLAIMS':
        tx.status['EMBEDDING'], tx.embedding = 'READY', [1.0, 0.0]
    job = repo.claim_next(analysis_version='v1')
    tx.exists = False
    if stage == 'EMBEDDING':
        assert not repo.complete_embedding(job_id=job['job_id'], lease_token=job['lease_token'], embedding=[1, 0])
    else:
        assert not repo.complete_claims(job_id=job['job_id'], lease_token=job['lease_token'], claims=[])
    assert not repo.fail(job_id=job['job_id'], lease_token=job['lease_token'], stage=stage, failure_code='TIMEOUT')
    assert repo.claim_next(analysis_version='v1') is None
    assert not any(sql.startswith('INSERT') for sql, _ in tx.statements)


def test_human_source_migration_only_broadens_player_kind_and_keeps_all_guards():
    """순방향 함수 교체가 원문·불변 참조·hash·벡터·claim 검증을 한 글자도 완화하지 않게 한다."""
    migrations = Path(__file__).parents[1] / 'migrations'
    original = (migrations / '006_create_speech_analysis.sql').read_text()
    upgrade = (migrations / '008_allow_public_human_speech_analysis.sql').read_text()
    start = original.index('CREATE OR REPLACE FUNCTION public.validate_speech_analysis()')
    original_function = original[start:original.index('\n$$;', start) + len('\n$$;')]
    start = upgrade.index('CREATE OR REPLACE FUNCTION public.validate_speech_analysis()')
    upgraded_function = upgrade[start:upgrade.index('\n$$;', start) + len('\n$$;')]
    expected = original_function.replace("p.kind = 'AI'", "p.kind IN ('HUMAN', 'AI')")
    assert upgraded_function == expected
    assert upgrade.count('BEGIN;') == 1 and upgrade.rstrip().endswith('COMMIT;')
    assert 'CREATE TABLE' not in upgrade and 'ALTER TABLE' not in upgrade
    assert 'UPDATE public.' not in upgrade and 'DELETE FROM' not in upgrade
    assert 'REFERENCES public.game_events (game_id, id, sequence) ON DELETE CASCADE' in original
    assert 'REFERENCES public.game_players (game_id, id) ON DELETE CASCADE' in original
