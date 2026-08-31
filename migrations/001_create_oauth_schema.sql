BEGIN;

-- UUID 기본값 생성을 위해 사용합니다. 이미 설치되어 있으면 아무 작업도 하지 않습니다.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text,
    display_name text,
    avatar_url text,
    is_active boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT users_email_not_blank
        CHECK (
            email IS NULL
            OR (btrim(email) <> '' AND char_length(email) <= 320)
        ),
    CONSTRAINT users_display_name_not_blank
        CHECK (
            display_name IS NULL
            OR (btrim(display_name) <> '' AND char_length(display_name) <= 120)
        ),
    CONSTRAINT users_avatar_url_is_https
        CHECK (
            avatar_url IS NULL
            OR (avatar_url ~ '^https://' AND char_length(avatar_url) <= 2048)
        ),
    CONSTRAINT users_updated_at_not_before_created_at
        CHECK (updated_at >= created_at)
);

CREATE TABLE IF NOT EXISTS public.oauth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    provider text NOT NULL,
    provider_subject text NOT NULL,
    provider_email text,
    email_verified boolean,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT oauth_identities_user_id_fkey
        FOREIGN KEY (user_id)
        REFERENCES public.users (id)
        ON DELETE CASCADE,
    CONSTRAINT oauth_identities_provider_subject_key
        UNIQUE (provider, provider_subject),
    CONSTRAINT oauth_identities_provider_format
        CHECK (provider ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    CONSTRAINT oauth_identities_provider_subject_not_blank
        CHECK (
            btrim(provider_subject) <> ''
            AND char_length(provider_subject) <= 512
        ),
    CONSTRAINT oauth_identities_provider_email_not_blank
        CHECK (
            provider_email IS NULL
            OR (btrim(provider_email) <> '' AND char_length(provider_email) <= 320)
        ),
    CONSTRAINT oauth_identities_updated_at_not_before_created_at
        CHECK (updated_at >= created_at)
);

-- 이메일은 연락처/프로필 속성일 뿐 계정 식별키가 아닙니다. 검색 보조용 비고유 인덱스입니다.
CREATE INDEX IF NOT EXISTS idx_users_email_lower
    ON public.users (lower(email))
    WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_oauth_identities_user_id
    ON public.oauth_identities (user_id);

CREATE OR REPLACE FUNCTION public.team4_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$function$;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_users_updated_at'
          AND tgrelid = 'public.users'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_users_updated_at
        BEFORE UPDATE ON public.users
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'set_oauth_identities_updated_at'
          AND tgrelid = 'public.oauth_identities'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER set_oauth_identities_updated_at
        BEFORE UPDATE ON public.oauth_identities
        FOR EACH ROW
        EXECUTE FUNCTION public.team4_set_updated_at();
    END IF;
END;
$migration$;

COMMENT ON TABLE public.users IS
    '애플리케이션 사용자. 이메일은 변경 가능하며 계정 식별키가 아니다.';
COMMENT ON COLUMN public.users.id IS '애플리케이션 내부 사용자 UUID.';
COMMENT ON COLUMN public.users.email IS
    '현재 대표 이메일. NULL 허용, 중복 허용, 인증/연결 식별에 사용하지 않는다.';
COMMENT ON COLUMN public.users.display_name IS 'OAuth 프로필에서 동기화할 수 있는 표시 이름.';
COMMENT ON COLUMN public.users.avatar_url IS 'OAuth 프로필에서 동기화할 수 있는 HTTPS 아바타 URL.';
COMMENT ON COLUMN public.users.is_active IS 'false이면 로그인 및 세션 생성을 거부할 수 있다.';
COMMENT ON COLUMN public.users.last_login_at IS '가장 최근 로그인 완료 시각.';
COMMENT ON COLUMN public.users.created_at IS '사용자 레코드 생성 시각.';
COMMENT ON COLUMN public.users.updated_at IS '사용자 레코드가 마지막으로 갱신된 시각.';

COMMENT ON TABLE public.oauth_identities IS
    '외부 OAuth 주체와 내부 사용자의 연결. access/refresh/id token은 저장하지 않는다.';
COMMENT ON COLUMN public.oauth_identities.id IS 'OAuth 연결 레코드 UUID.';
COMMENT ON COLUMN public.oauth_identities.user_id IS '연결된 내부 사용자 UUID.';
COMMENT ON COLUMN public.oauth_identities.provider IS '정규화된 OAuth 제공자 코드(예: google).';
COMMENT ON COLUMN public.oauth_identities.provider_subject IS
    '제공자가 발급한 불변 subject(sub) 값. provider와 함께 유일하다.';
COMMENT ON COLUMN public.oauth_identities.provider_email IS
    '제공자가 마지막으로 전달한 이메일 스냅샷. NULL/중복 허용, 식별키가 아니다.';
COMMENT ON COLUMN public.oauth_identities.email_verified IS
    '제공자가 마지막 로그인에서 전달한 이메일 검증 상태.';
COMMENT ON COLUMN public.oauth_identities.last_login_at IS '이 OAuth 연결로 로그인한 최근 시각.';
COMMENT ON COLUMN public.oauth_identities.created_at IS 'OAuth 연결 생성 시각.';
COMMENT ON COLUMN public.oauth_identities.updated_at IS 'OAuth 연결이 마지막으로 갱신된 시각.';

COMMENT ON FUNCTION public.team4_set_updated_at() IS
    'UPDATE 시 updated_at을 데이터베이스 현재 시각으로 갱신한다.';

COMMIT;
