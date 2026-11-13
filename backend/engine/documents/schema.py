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
    -- 用户给资料打的标签（笔记/面经常用），JSON 数组
    tags_json       TEXT NOT NULL DEFAULT '[]',
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
    -- 投递时用的简历：存摘要与指纹，不存整份 Markdown（避免体积失控）
    resume_excerpt     TEXT NOT NULL DEFAULT '',
    resume_hash        TEXT NOT NULL DEFAULT '',
    resume_saved_at    REAL,
    resume_snapshot_id TEXT,
    next_action_at     REAL,
    note               TEXT NOT NULL DEFAULT '',
    created_at         REAL NOT NULL,
    updated_at         REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_doc ON applications(user_id, doc_id);
CREATE INDEX IF NOT EXISTS idx_applications_stage ON applications(user_id, stage, updated_at DESC);

-- 投递状态变化的留痕：谁在什么时候从哪个阶段走到哪个阶段
CREATE TABLE IF NOT EXISTS application_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_stage     TEXT NOT NULL DEFAULT '',
    to_stage       TEXT NOT NULL,
    note           TEXT NOT NULL DEFAULT '',
    created_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_application_events ON application_events(application_id, id DESC);

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
    -- 内容版本：作者每次改内容都 +1，帮助票与评论按版本归属
    revision        INTEGER NOT NULL DEFAULT 1,
    created_at      REAL NOT NULL,
    published_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_cards_status ON public_cards(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_cards_company ON public_cards(company, role, status);
CREATE INDEX IF NOT EXISTS idx_cards_kind ON public_cards(kind, status, published_at DESC);

-- 每人对同一张卡片只能点一次「有帮助」，重复点击不重复计数
CREATE TABLE IF NOT EXISTS card_votes (
    card_id    TEXT NOT NULL REFERENCES public_cards(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    PRIMARY KEY(card_id, user_id)
);

-- 举报：同一人同一卡一次；累计达标后卡片自动回到待审（先从列表隐藏）
-- status 是处理状态：open 待管理员处理，resolved 已处理（保留记录便于复盘）
CREATE TABLE IF NOT EXISTS card_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    TEXT NOT NULL REFERENCES public_cards(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'open',
    handled_by TEXT,
    handled_at REAL,
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_card_report_owner ON card_reports(card_id, user_id);
CREATE INDEX IF NOT EXISTS idx_card_reports_card ON card_reports(card_id, id DESC);

-- 评论：挂在已公开的卡片下，同样匿名；被举报达阈值先撤下，等管理员处理
CREATE TABLE IF NOT EXISTS card_comments (
    id           TEXT PRIMARY KEY,
    card_id      TEXT NOT NULL REFERENCES public_cards(id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anon_id      TEXT NOT NULL REFERENCES anon_identities(id),
    body         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'public',
    report_count INTEGER NOT NULL DEFAULT 0,
    revision     INTEGER NOT NULL DEFAULT 1,
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_card ON card_comments(card_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_status ON card_comments(status, id DESC);

-- 内容版本快照：作者每次改内容留一份，供作者/管理员查历史与对比上一版
CREATE TABLE IF NOT EXISTS card_revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    TEXT NOT NULL REFERENCES public_cards(id) ON DELETE CASCADE,
    revision   INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    body_md    TEXT NOT NULL DEFAULT '',
    company    TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL DEFAULT '',
    round      TEXT NOT NULL DEFAULT '',
    tags_json  TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_card_revisions_version ON card_revisions(card_id, revision);

-- 评论举报：一人一条评论一次，避免一个人刷举报把评论顶掉
CREATE TABLE IF NOT EXISTS comment_reports (
    comment_id TEXT NOT NULL REFERENCES card_comments(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(comment_id, user_id)
);

CREATE TABLE IF NOT EXISTS feed_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    url         TEXT NOT NULL,
    tier        INTEGER NOT NULL DEFAULT 3,
    enabled     INTEGER NOT NULL DEFAULT 1,
    license_note TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
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
    # 旧库缺列时补齐（SQLite 不支持 ADD COLUMN IF NOT EXISTS，靠 pragma 判断）
    columns = {row[1] for row in db.execute("PRAGMA table_info(feed_sources)")}
    if "config_json" not in columns:
        db.execute("ALTER TABLE feed_sources ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'")

    # 举报处理状态是后加的：旧库补列，已有举报按待处理算
    report_columns = {row[1] for row in db.execute("PRAGMA table_info(card_reports)")}
    if "status" not in report_columns:
        db.execute("ALTER TABLE card_reports ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
    if "handled_by" not in report_columns:
        db.execute("ALTER TABLE card_reports ADD COLUMN handled_by TEXT")
    if "handled_at" not in report_columns:
        db.execute("ALTER TABLE card_reports ADD COLUMN handled_at REAL")
    # 索引放在补列之后建，否则旧库会在 executescript 阶段报 no such column
    db.execute("CREATE INDEX IF NOT EXISTS idx_card_reports_status ON card_reports(status, id DESC)")

    # 早期邮箱注册实验留下的两张表，代码零引用；确认无数据后清掉，避免以后误以为有功能
    for stale in ("registration_codes", "registration_send_limits"):
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (stale,)
        ).fetchone():
            db.execute(f"DROP TABLE IF EXISTS {stale}")

    # 资料标签列是后加的：旧资料默认没有标签
    doc_columns = {row[1] for row in db.execute("PRAGMA table_info(documents)")}
    if "tags_json" not in doc_columns:
        db.execute("ALTER TABLE documents ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")

    # 投递关联简历的字段是后加的：旧记录留空，不伪造当时的简历
    app_columns = {row[1] for row in db.execute("PRAGMA table_info(applications)")}
    for column, ddl in (
        ("resume_excerpt", "ALTER TABLE applications ADD COLUMN resume_excerpt TEXT NOT NULL DEFAULT ''"),
        ("resume_hash", "ALTER TABLE applications ADD COLUMN resume_hash TEXT NOT NULL DEFAULT ''"),
        ("resume_saved_at", "ALTER TABLE applications ADD COLUMN resume_saved_at REAL"),
    ):
        if column not in app_columns:
            db.execute(ddl)

    # 内容版本列是后加的：旧卡片与旧评论都按第 1 版算
    card_columns = {row[1] for row in db.execute("PRAGMA table_info(public_cards)")}
    if "revision" not in card_columns:
        db.execute("ALTER TABLE public_cards ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
    comment_columns = {row[1] for row in db.execute("PRAGMA table_info(card_comments)")}
    if "revision" not in comment_columns:
        db.execute("ALTER TABLE card_comments ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
