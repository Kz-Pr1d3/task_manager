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
CREATE INDEX IF NOT EXISTS tasks_parent_id_idx
    ON tasks (parent_id);
CREATE INDEX IF NOT EXISTS tasks_user_list_active_idx
    ON tasks (user_id, list_id)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS tasks_list_pagination_idx
    ON tasks (user_id, list_id, created_at, id)
    WHERE parent_id IS NULL AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS tasks_today_next7_idx
    ON tasks (user_id, due_date, id)
    WHERE deleted_at IS NULL
      AND status = 'active'
      AND parent_id IS NULL;
CREATE INDEX IF NOT EXISTS tasks_completed_idx
    ON tasks (user_id, completed_at DESC, id DESC)
    WHERE deleted_at IS NULL
      AND parent_id IS NULL
      AND status = 'completed';
CREATE INDEX IF NOT EXISTS tasks_trash_idx
    ON tasks (user_id, deleted_at DESC, id DESC)
    WHERE deleted_at IS NOT NULL
      AND parent_id IS NULL;

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
