CREATE TABLE IF NOT EXISTS users (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(255) UNIQUE NOT NULL,
    password   VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO users (email, password) VALUES ('test_user@test.com', 'super_strong_pass');

---------------------------- lists -----------------------------------------
CREATE TABLE IF NOT EXISTS lists (
    id         SERIAL PRIMARY KEY,
    user_id    INT REFERENCES users (id) ON DELETE CASCADE,
    type       VARCHAR(20)  NOT NULL,
    name       VARCHAR(255) NOT NULL,
    position   INT,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT lists_type_check CHECK (
        type IN ('inbox', 'user')
    ),
    CONSTRAINT lists_user_type_check CHECK (
        (type = 'inbox' AND user_id IS NULL)
        OR (type = 'user' AND user_id IS NOT NULL)
    )
);

-- один Inbox на всю систему
CREATE UNIQUE INDEX IF NOT EXISTS lists_system_type_unique
    ON lists (type)
    WHERE user_id IS NULL;

CREATE INDEX IF NOT EXISTS lists_user_position_idx
    ON lists (user_id, position)
    WHERE type = 'user';

---------------------------- lists -----------------------------------------

-- =============================================================================
-- tasks
-- лимит 100 задач на list, лимит 5 user-списков — service layer (HTTP 409)
-- =============================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id               SERIAL PRIMARY KEY,
    user_id          INT          NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    list_id          INT          NOT NULL REFERENCES lists (id),
    parent_id        INT          REFERENCES tasks (id) ON DELETE CASCADE,
    previous_list_id INT,         -- без FK: user list мог быть hard delete
    title            VARCHAR(50)  NOT NULL,
    description      TEXT,
    priority         VARCHAR(10),
    due_date         TIMESTAMPTZ,
    status           VARCHAR(20)  NOT NULL DEFAULT 'active',
    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    CONSTRAINT tasks_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT tasks_priority_check CHECK (
        priority IS NULL OR priority IN ('low', 'medium', 'high')
    ),
    CONSTRAINT tasks_status_check CHECK (
        status IN ('active', 'completed')
    )
);
CREATE INDEX IF NOT EXISTS tasks_user_list_active_idx
    ON tasks (user_id, list_id)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS tasks_list_pagination_idx
    ON tasks (user_id, list_id, created_at, id)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS tasks_today_next7_idx
    ON tasks (user_id, due_date, id)
    WHERE deleted_at IS NULL
      AND status = 'active';
CREATE INDEX IF NOT EXISTS tasks_completed_idx
    ON tasks (user_id, completed_at DESC, id DESC)
    WHERE deleted_at IS NULL
      AND status = 'completed';
CREATE INDEX IF NOT EXISTS tasks_trash_idx
    ON tasks (user_id, deleted_at DESC, id DESC)
    WHERE deleted_at IS NOT NULL;

-- =============================================================================
-- notification
-- =============================================================================
CREATE TABLE IF NOT EXISTS notification (
    id            BIGSERIAL PRIMARY KEY,
    event_id      VARCHAR(160) NOT NULL,
    type          VARCHAR(64)  NOT NULL,
    category      VARCHAR(32)  NOT NULL DEFAULT 'tasks',
    severity      VARCHAR(16)  NOT NULL DEFAULT 'normal',

    actor_id      INT REFERENCES users (id) ON DELETE SET NULL,
    recipient_id  INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,

    entity_type   VARCHAR(32),
    entity_id     VARCHAR(64),

    title         TEXT NOT NULL,
    body          TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    deep_link     TEXT,

    grouping_key  VARCHAR(256),
    group_count   INTEGER NOT NULL DEFAULT 1,

    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at       TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,

    CONSTRAINT uq_notification_event_recipient
        UNIQUE (event_id, recipient_id),
    CONSTRAINT ck_notification_severity
        CHECK (severity IN ('normal', 'important')),
    CONSTRAINT ck_notification_group_count
        CHECK (group_count > 0)
);

CREATE INDEX IF NOT EXISTS ix_notification_recipient_created
    ON notification (recipient_id, id DESC);

CREATE INDEX IF NOT EXISTS ix_notification_recipient_unread
    ON notification (recipient_id, id DESC)
    WHERE read_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_notification_recipient_category
    ON notification (recipient_id, category, id DESC);

CREATE INDEX IF NOT EXISTS ix_notification_grouping
    ON notification (recipient_id, grouping_key, id DESC)
    WHERE grouping_key IS NOT NULL;

-- =============================================================================
-- task_attachment (S3 / MinIO вложения)
-- лимит файлов на задачу — service/repo (HTTP 409)
-- =============================================================================
CREATE TABLE IF NOT EXISTS task_attachment (
    id              BIGSERIAL PRIMARY KEY,
    task_id         INT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    user_id         INT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    storage_key     TEXT NOT NULL,
    original_name   VARCHAR(255) NOT NULL,
    content_type    VARCHAR(127) NOT NULL,
    size_bytes      BIGINT,
    status          VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at        TIMESTAMPTZ,
    CONSTRAINT task_attachment_status_check
        CHECK (status IN ('pending', 'ready', 'failed')),
    CONSTRAINT task_attachment_size_nonneg
        CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE INDEX IF NOT EXISTS task_attachment_task_idx
    ON task_attachment (task_id, created_at DESC);

CREATE INDEX IF NOT EXISTS task_attachment_pending_idx
    ON task_attachment (status, created_at)
    WHERE status = 'pending';

-- =============================================================================
-- seed: системные списки
-- =============================================================================
INSERT INTO lists (id, user_id, type, name, position)
VALUES
    (1, NULL, 'inbox', 'Входящие', NULL)
ON CONFLICT DO NOTHING;
SELECT setval(
    pg_get_serial_sequence('lists', 'id'),
    (SELECT COALESCE(MAX(id), 1) FROM lists)
);
