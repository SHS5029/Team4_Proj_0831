-- AI 마피아 mystery-v1 최소 정적 콘텐츠를 등록한다.
-- 이 migration은 정본에 등록된 시나리오 5개, 시나리오별 활성 알리바이 9개와
-- 관찰 9개, 그리고 게임 실행에 필요한 최소 활성 persona 한 개를 제공한다.
-- 고정 ID와 template key를 기준으로 upsert하므로 재실행해도 행을 중복 생성하지 않는다.
BEGIN;

WITH scenario_seed(id, version, title, background, victim, locations) AS (
    VALUES
        (
            'BLACKOUT_STUDIO',
            'scenario-v1',
            '정전된 방송국',
            '생방송 준비 중 정전된 방송국에서 PD가 사망했다.',
            '생방송 PD',
            '["스튜디오", "조정실", "분장실", "대기실", "장비실"]'::jsonb
        ),
        (
            'SNOWBOUND_LODGE',
            'scenario-v1',
            '눈 내리는 산장',
            '폭설로 고립된 산장에서 관리인이 약병 사건으로 사망했다.',
            '산장 관리인',
            '["거실", "주방", "복도", "관리인 방", "창고"]'::jsonb
        ),
        (
            'CLOSING_MUSEUM',
            'scenario-v1',
            '폐관 직전의 박물관',
            '폐관 직전 박물관에서 전시 담당자가 사망했다.',
            '전시 담당자',
            '["중앙 전시장", "보안실", "안내 데스크", "복원실", "직원 휴게실"]'::jsonb
        ),
        (
            'LAST_BANQUET_GUEST',
            'scenario-v1',
            '호텔 만찬의 마지막 손님',
            '비공개 호텔 만찬 도중 주최자가 사망했다.',
            '만찬 주최자',
            '["연회장", "주방", "로비", "복도", "VIP룸"]'::jsonb
        ),
        (
            'STOPPED_NIGHT_TRAIN',
            'scenario-v1',
            '멈춰 선 야간열차',
            '열차가 터널에 멈춘 사이 승무원이 사망했다.',
            '열차 승무원',
            '["승무원실", "객차", "식당칸", "연결 통로", "화물칸"]'::jsonb
        )
)
INSERT INTO public.scenario_catalog (
    id,
    version,
    title,
    background,
    victim,
    locations,
    active,
    content_hash,
    approved_at
)
SELECT
    id,
    version,
    title,
    background,
    victim,
    locations,
    true,
    repeat('0', 64),
    TIMESTAMPTZ '2026-09-03 00:00:00+00'
FROM scenario_seed
ON CONFLICT (id) DO UPDATE
SET version = EXCLUDED.version,
    title = EXCLUDED.title,
    background = EXCLUDED.background,
    victim = EXCLUDED.victim,
    locations = EXCLUDED.locations,
    active = EXCLUDED.active,
    approved_at = EXCLUDED.approved_at;

WITH template_seed(
    scenario_id,
    template_kind,
    template_key,
    text_template,
    subject_mode
) AS (
    VALUES
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_01', '정전 당시 조정실에서 예비 전원 장치를 확인하고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_02', '생방송 원고를 정리하며 스튜디오 뒤편에 머물렀다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_03', '분장실에서 의상과 소품 목록을 확인하고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_04', '대기실에서 출연 순서를 다시 읽고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_05', '장비실 입구에서 케이블 상자를 정리하고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_06', '스튜디오에서 바닥 표시와 카메라 동선을 점검했다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_07', '복도에서 전달받은 방송 자료를 분류하고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_08', '조정실 옆에서 헤드셋의 작동 상태를 확인했다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'ALIBI', 'ALIBI_09', '대기실 책상에서 출연자 안내문을 작성하고 있었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_01', '정전 직전 장비실 쪽으로 이동하는 사람을 봤다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_02', '조정실 문이 평소보다 오래 열려 있는 것을 봤다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_03', '분장실 근처에 놓인 낯선 케이블 묶음을 발견했다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_04', '스튜디오 뒤편에서 금속 물체가 떨어지는 소리를 들었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_05', '대기실 조명이 다른 곳보다 늦게 꺼지는 것을 봤다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_06', '복도에서 서둘러 서류를 감추는 듯한 사람을 봤다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_07', '장비실 손잡이에 묻은 검은 얼룩을 발견했다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_08', '조정실 안에서 짧게 언쟁하는 목소리를 들었다.', 'NONE'),
        ('BLACKOUT_STUDIO', 'OBSERVATION', 'OBSERVATION_09', '정전 뒤 스튜디오 출입문 하나가 열려 있는 것을 봤다.', 'NONE'),

        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_01', '거실 난로 옆에서 젖은 장갑을 말리고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_02', '주방에서 남은 식재료와 식기를 정리하고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_03', '복도 창가에서 바깥의 적설 상태를 살펴봤다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_04', '창고 앞에서 난방용 장작의 수량을 확인했다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_05', '거실 탁자에서 산장 안내 책자를 읽고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_06', '주방 입구에서 따뜻한 물을 준비하고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_07', '관리인 방과 떨어진 계단에서 눈을 털고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_08', '복도 끝에서 비상등의 상태를 점검하고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'ALIBI', 'ALIBI_09', '창고 안쪽에서 여분 담요를 찾고 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_01', '관리인 방에서 나와 복도로 향하는 사람을 봤다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_02', '주방 선반에 뚜껑이 열린 작은 병이 놓인 것을 봤다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_03', '창고 바닥에 평소와 다른 젖은 발자국이 남아 있었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_04', '거실에서 누군가 관리인과 낮게 말다툼하는 소리를 들었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_05', '복도 창문 하나의 잠금장치가 풀려 있는 것을 발견했다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_06', '주방 근처에서 급히 손을 씻는 사람을 봤다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_07', '관리인 방 앞에 떨어진 종이 포장지를 발견했다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_08', '창고 문이 닫힌 뒤 안에서 물건이 움직이는 소리를 들었다.', 'NONE'),
        ('SNOWBOUND_LODGE', 'OBSERVATION', 'OBSERVATION_09', '거실 탁자 아래에 비어 있는 찻잔 하나가 놓여 있었다.', 'NONE'),

        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_01', '중앙 전시장에서 안내 표지의 위치를 확인하고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_02', '보안실 앞에서 폐관 점검표를 읽고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_03', '안내 데스크에서 분실물 목록을 정리하고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_04', '복원실에서 포장재와 작업 도구를 정돈하고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_05', '직원 휴게실에서 개인 물품을 챙기고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_06', '중앙 전시장 출구에서 남은 관람객을 안내했다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_07', '안내 데스크 옆에서 전시 안내서를 묶고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_08', '복원실 입구에서 보호 장갑을 정리하고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'ALIBI', 'ALIBI_09', '직원 통로에서 폐관 방송을 기다리고 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_01', '보안실 근처에서 짧은 다툼 소리를 들었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_02', '복원실 문 앞에 낯선 천 조각이 떨어져 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_03', '중앙 전시장의 진열장 하나에 손자국이 남아 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_04', '안내 데스크 뒤편으로 급히 이동하는 사람을 봤다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_05', '직원 휴게실 사물함 하나가 반쯤 열린 것을 발견했다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_06', '보안실 화면 하나가 잠시 꺼지는 것을 봤다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_07', '복원실 안에서 유리병이 부딪히는 소리를 들었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_08', '중앙 전시장 바닥에 접힌 점검표가 놓여 있었다.', 'NONE'),
        ('CLOSING_MUSEUM', 'OBSERVATION', 'OBSERVATION_09', '폐관 방송 뒤에도 안내 데스크 전화가 잠시 사용됐다.', 'NONE'),

        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_01', '연회장에서 식기 배치를 살펴보며 자리를 지키고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_02', '주방 입구에서 준비된 요리 순서를 확인하고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_03', '로비에서 맡겨 둔 외투를 찾고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_04', '복도 창가에서 행사 안내문을 읽고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_05', 'VIP룸 앞에서 빈 잔을 정리하고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_06', '연회장 뒤편에서 좌석표를 다시 확인했다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_07', '주방에서 사용한 쟁반을 정돈하고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_08', '로비 안내대에서 차량 호출을 기다리고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'ALIBI', 'ALIBI_09', '복도 끝에서 휴대품을 가방에 넣고 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_01', '누군가 주최자와 대화한 뒤 복도로 급히 나가는 것을 봤다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_02', 'VIP룸 탁자에 주인이 없는 잔 하나가 놓여 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_03', '주방 입구에서 작은 봉투를 숨기는 듯한 사람을 봤다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_04', '연회장 뒤편에서 의자가 끌리는 소리를 들었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_05', '로비 바닥에 행사 명찰 하나가 떨어져 있었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_06', '복도 조명이 잠시 깜빡인 뒤 문 하나가 닫혔다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_07', '주방 선반에서 라벨이 없는 병을 발견했다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_08', 'VIP룸 앞에서 낮게 언쟁하는 두 목소리를 들었다.', 'NONE'),
        ('LAST_BANQUET_GUEST', 'OBSERVATION', 'OBSERVATION_09', '연회장 테이블 아래에 접힌 메모가 놓여 있었다.', 'NONE'),

        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_01', '열차가 멈췄을 때 객차 좌석에서 짐을 지키고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_02', '식당칸에서 사용한 컵과 접시를 정리하고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_03', '연결 통로 입구에서 흔들리는 문을 붙잡고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_04', '화물칸 앞에서 자신의 가방 표식을 확인했다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_05', '객차 선반에서 담요를 꺼내고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_06', '식당칸 창가에서 터널 밖 상황을 기다리고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_07', '승무원실과 떨어진 객차에서 안내 방송을 듣고 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_08', '연결 통로에서 떨어진 소지품을 주워 정리했다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'ALIBI', 'ALIBI_09', '화물칸 입구에서 고정 장치의 상태를 살펴봤다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_01', '연결 통로에서 승무원실 쪽으로 이동하는 사람을 봤다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_02', '식당칸 탁자에 반쯤 비워진 물병이 놓여 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_03', '화물칸 문이 잠시 열렸다가 닫히는 소리를 들었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_04', '객차 바닥에서 승무원용 표식 조각을 발견했다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_05', '연결 통로 조명이 꺼진 사이 누군가 지나가는 기척을 느꼈다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_06', '승무원실 앞 손잡이에 젖은 자국이 남아 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_07', '식당칸에서 낮은 목소리로 다투는 소리를 들었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_08', '화물칸 앞에 주인이 확인되지 않은 장갑이 놓여 있었다.', 'NONE'),
        ('STOPPED_NIGHT_TRAIN', 'OBSERVATION', 'OBSERVATION_09', '열차가 멈춘 뒤 객차 사이 문 하나가 열린 채 남아 있었다.', 'NONE')
)
INSERT INTO public.scenario_templates (
    scenario_id,
    template_kind,
    template_key,
    text_template,
    subject_mode,
    active
)
SELECT
    scenario_id,
    template_kind,
    template_key,
    text_template,
    subject_mode,
    true
FROM template_seed
ON CONFLICT (scenario_id, template_kind, template_key) DO UPDATE
SET text_template = EXCLUDED.text_template,
    subject_mode = EXCLUDED.subject_mode,
    active = EXCLUDED.active;

-- 콘텐츠 hash는 공개 시나리오와 현재 활성 template 전체를 안정적인 key 순서로
-- 직렬화해 계산한다. 운영 중 임의로 활성 문장을 추가하면 hash도 달라져 검수 대상이 된다.
UPDATE public.scenario_catalog AS scenario
SET content_hash = encode(
        digest(
            jsonb_build_object(
                'id', scenario.id,
                'version', scenario.version,
                'title', scenario.title,
                'background', scenario.background,
                'victim', scenario.victim,
                'locations', scenario.locations,
                'templates', (
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'kind', template.template_kind,
                            'key', template.template_key,
                            'text', template.text_template,
                            'subject_mode', template.subject_mode
                        )
                        ORDER BY template.template_kind, template.template_key
                    )
                    FROM public.scenario_templates AS template
                    WHERE template.scenario_id = scenario.id
                      AND template.active = true
                )
            )::text,
            'sha256'
        ),
        'hex'
    ),
    approved_at = TIMESTAMPTZ '2026-09-03 00:00:00+00',
    active = true
WHERE scenario.id IN (
    'BLACKOUT_STUDIO',
    'SNOWBOUND_LODGE',
    'CLOSING_MUSEUM',
    'LAST_BANQUET_GUEST',
    'STOPPED_NIGHT_TRAIN'
);

WITH persona_seed AS (
    SELECT
        'BALANCED_OBSERVER'::varchar(64) AS id,
        'mystery-v1'::varchar(32) AS version,
        '차분한 관찰자'::varchar(40) AS display_name,
        '공개된 사실을 짧게 정리하고 단정하지 않는 말투를 사용한다.'::varchar(240)
            AS speech_style,
        '대화 중 드러난 작은 차이를 기록하고 다른 사람의 설명을 차분히 비교한다.'::varchar(500)
            AS backstory,
        jsonb_build_object(
            'sociability', 0.5,
            'assertiveness', 0.5,
            'suspicion', 0.5,
            'deception', 0.5,
            'risk_tolerance', 0.5,
            'memory_recall', 0.5,
            'reasoning_skill', 0.5,
            'emotionality', 0.5,
            'cooperativeness', 0.5,
            'verbosity', 0.5
        ) AS parameters
)
INSERT INTO public.agent_personas (
    id,
    version,
    display_name,
    speech_style,
    backstory,
    parameters,
    active,
    content_hash
)
SELECT
    id,
    version,
    display_name,
    speech_style,
    backstory,
    parameters,
    true,
    encode(
        digest(
            jsonb_build_object(
                'id', id,
                'version', version,
                'display_name', display_name,
                'speech_style', speech_style,
                'backstory', backstory,
                'parameters', parameters
            )::text,
            'sha256'
        ),
        'hex'
    )
FROM persona_seed
ON CONFLICT (id) DO UPDATE
SET version = EXCLUDED.version,
    display_name = EXCLUDED.display_name,
    speech_style = EXCLUDED.speech_style,
    backstory = EXCLUDED.backstory,
    parameters = EXCLUDED.parameters,
    active = EXCLUDED.active,
    content_hash = EXCLUDED.content_hash;

COMMIT;
