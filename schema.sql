CREATE TABLE IF NOT EXISTS users (
    telegram_id    BIGINT PRIMARY KEY,
    username       TEXT,
    currency       TEXT        NOT NULL DEFAULT 'USD',
    monthly_budget NUMERIC(12, 2),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expenses (
    id          BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT         NOT NULL REFERENCES users (telegram_id) ON DELETE CASCADE,
    amount      NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    currency    TEXT           NOT NULL,
    category    TEXT           NOT NULL,
    note        TEXT,
    raw_text    TEXT,
    source      TEXT           NOT NULL DEFAULT 'voice',
    spent_at    TIMESTAMPTZ    NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS expenses_user_spent_idx
    ON expenses (telegram_id, spent_at DESC);
