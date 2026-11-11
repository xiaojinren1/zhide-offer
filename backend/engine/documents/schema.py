"""资料层建表与幂等迁移。

调用约定：在 `core.accounts.connection()` 里执行一次 `ensure(db)`，与现有
`_SCHEMA` 的做法保持一致（每个连接执行 `CREATE ... IF NOT EXISTS`）。
所有语句必须幂等：重复执行不报错、不改动已有数据。
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

# 文档、分块、投递、社群、信源一次建全：后续阶段只加列，不再新增迁移入口。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    user_id         TEXT REFERENCES users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_key      TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    salary_text     TEXT NOT NULL DEFAULT '',
    salary_min      INTEGER,
    salary_max      INTEGER,
    experience      TEXT NOT NULL DEFAULT '',
    education       TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    published_at    REAL,
    fetched_at      REAL NOT NULL,
    content_md      TEXT NOT NULL DEFAULT '',
    structured_json TEXT NOT NULL DEFAULT '{}',
    visibility      TEXT NOT NULL DEFAULT 'private',
    review_note     TEXT NOT NULL DEFAULT '',
    reviewed_by     TEXT,
    reviewed_at     REAL,
    license_note    TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_dedupe
    ON documents(COALESCE(user_id, ''), source_key);
CREATE INDEX IF NOT EXISTS idx_documents_owner
    ON documents(COALESCE(user_id, ''), kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_visibility
    ON documents(visibility, published_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     TEXT,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    text_tokens TEXT NOT NULL,
    tokens      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON knowledge_chunks(doc_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    text_tokens,
    chunk_id UNINDEXED
);

CREATE TABLE IF NOT EXISTS applications (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doc_id             TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage              TEXT NOT NULL DEFAULT 'saved',
    resume_snapshot_id TEXT,
    next_action_at     REAL,
    note               TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_doc ON applications(user_id, doc_id);
CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications(user_id, stage, updated_at DESC);

CREATE TABLE IF NOT EXISTS anon_identities (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anon_owner ON anon_identities(user_id);

CREATE TABLE IF NOT EXISTS public_cards (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anon_id         TEXT NOT NULL REFERENCES anon_identities(id),
    kind            TEXT NOT NULL,
    company         TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT '',
    round           TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL,
    body_md         TEXT NOT NULL,
    tags_json       TEXT NOT NULL DEFAULT '[]',
    structured_json TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    review_note     TEXT NOT NULL DEFAULT '',
    reviewed_by     TEXT,
    reviewed_at     REAL,
    helpful_count   INTEGER NOT NULL DEFAULT 0,
    report_count    INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    published_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_cards_status ON public_cards(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_cards_company ON public_cards(company, role, status);

CREATE TABLE IF NOT EXISTS feed_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    url         TEXT NOT NULL,
    tier        INTEGER NOT NULL DEFAULT 3,
    enabled     INTEGER NOT NULL DEFAULT 1,
    license_note TEXT NOT NULL DEFAULT '',
    last_run_at REAL,
    last_status TEXT NOT NULL DEFAULT ''
);
"""


def ensure(db: sqlite3.Connection) -> None:
    """建表与索引；重复调用无副作用。

    FTS5 不可用时直接抛出：检索是核心能力，静默退化成普通表会让搜索结果
    变成"看起来对"的错误结果，违反项目 `后端/RULES.md` 的硬性规则。
    """
    db.executescript(_SCHEMA)
