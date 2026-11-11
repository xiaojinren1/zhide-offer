"""资料的入库、去重、分块与检索。

对外四个动作：写（`upsert_document`）、读（`get_document` / `list_documents`）、
搜（`search`）、删（`delete_document`）。权限规则集中在这里：
**公共池（`user_id` 为 NULL）全站可读，私有资料只有本人可读，`rejected` 任何入口都不可见。**
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from . import dedupe, normalize, text as text_util

CHUNK_MAX_CHARS = 600
CHUNK_OVERLAP = 80


@dataclass
class DocumentDraft:
    """一次入库的入参。字段留空表示"不覆盖库里已有的值"。"""

    kind: str = "jd"
    source: str = "manual"
    title: str = ""
    company: str = ""
    role: str = ""
    city: str = ""
    salary_text: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    experience: str = ""
    education: str = ""
    url: str = ""
    published_at: float | None = None
    content_md: str = ""
    structured: dict[str, Any] = field(default_factory=dict)
    visibility: str = ""
    license_note: str = ""
    user_id: str | None = None

    def resolved_key(self) -> str:
        return dedupe.source_key(
            url=self.url,
            title=self.title,
            company=self.company,
            role=self.role,
            content=self.content_md,
        )


def split_chunks(content: object) -> list[str]:
    """按空行分段，再按长度聚合；相邻块保留少量重叠，避免边界处的句子搜不到。"""
    body = text_util.normalize_text(content)
    if not body:
        return []

    paragraphs = [part.strip() for part in body.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 1 <= CHUNK_MAX_CHARS:
            current = f"{current}\n{paragraph}"
        else:
            chunks.append(current)
            tail = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else current
            current = f"{tail}\n{paragraph}"

    if current:
        while len(current) > CHUNK_MAX_CHARS:
            chunks.append(current[:CHUNK_MAX_CHARS])
            current = current[CHUNK_MAX_CHARS - CHUNK_OVERLAP:]
        if current:
            chunks.append(current)
    return chunks


def _owner(user_id: str | None) -> str:
    return user_id or ""


def get_document(
    db: sqlite3.Connection, doc_id: str, *, user_id: str | None
) -> sqlite3.Row | None:
    """按可见性取单条资料：本人私有、或公共池、或已公开。"""
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row is None:
        return None
    if row["visibility"] == "rejected":
        return None
    if row["visibility"] == "public":
        return row
    return row if _owner(row["user_id"]) == _owner(user_id) else None


def list_documents(
    db: sqlite3.Connection,
    *,
    user_id: str | None,
    kinds: Iterable[str] | None = None,
    visibility: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """列出本人资料与公共资料；`visibility` 只作为附加过滤条件。"""
    clauses = ["visibility != 'rejected'", "(COALESCE(user_id,'') = ? OR visibility = 'public')"]
    params: list[Any] = [_owner(user_id)]

    kinds = list(kinds or [])
    if kinds:
        clauses.append(f"kind IN ({','.join('?' for _ in kinds)})")
        params.extend(kinds)
    if visibility:
        clauses.append("visibility = ?")
        params.append(visibility)

    params.extend([max(1, min(int(limit), 100)), max(0, int(offset))])
    sql = (
        "SELECT * FROM documents WHERE " + " AND ".join(clauses)
        + " ORDER BY COALESCE(published_at, updated_at) DESC LIMIT ? OFFSET ?"
    )
    return db.execute(sql, params).fetchall()


def upsert_document(db: sqlite3.Connection, draft: DocumentDraft) -> tuple[str, bool]:
    """按去重键写入或更新，返回 (doc_id, 是否新建)。

    更新时只覆盖草稿里给了值的字段：采集刷新不应抹掉用户手工补的标题或备注。
    """
    key = draft.resolved_key()
    if not key:
        raise ValueError("资料缺少去重依据：url、标题或正文至少要有一项")

    now = time.time()
    kind = normalize.clean_choice(draft.kind, normalize.DOC_KINDS, "jd")
    source = normalize.clean_choice(draft.source, normalize.DOC_SOURCES, "manual")
    existing = db.execute(
        "SELECT * FROM documents WHERE COALESCE(user_id,'') = ? AND source_key = ?",
        (_owner(draft.user_id), key),
    ).fetchone()

    if existing is not None:
        updates: dict[str, Any] = {}
        simple_fields = {
            "title": text_util.normalize_text(draft.title),
            "company": text_util.normalize_text(draft.company),
            "role": text_util.normalize_text(draft.role),
            "city": normalize.normalize_city(draft.city),
            "salary_text": draft.salary_text,
            "experience": draft.experience,
            "education": draft.education,
            "url": draft.url,
            "content_md": text_util.normalize_text(draft.content_md),
            "license_note": draft.license_note,
        }
        for column, value in simple_fields.items():
            if value:
                updates[column] = value
        if draft.salary_min is not None:
            updates["salary_min"] = draft.salary_min
        if draft.salary_max is not None:
            updates["salary_max"] = draft.salary_max
        if draft.published_at is not None:
            updates["published_at"] = draft.published_at
        if draft.structured:
            updates["structured_json"] = json.dumps(draft.structured, ensure_ascii=False)
        if draft.visibility:
            updates["visibility"] = draft.visibility

        updates["fetched_at"] = now
        updates["updated_at"] = now
        assignments = ", ".join(f"{column} = ?" for column in updates)
        db.execute(
            f"UPDATE documents SET {assignments} WHERE id = ?",
            [*updates.values(), existing["id"]],
        )
        if draft.content_md or draft.structured:
            replace_chunks(db, existing["id"], draft.user_id, draft.content_md
                           or existing["content_md"])
        return existing["id"], False

    doc_id = uuid4().hex
    # 没有 owner 的资料属于公共池：公共池默认公开，否则它会是一条谁都看不到的记录
    default_visibility = "public" if draft.user_id is None else "private"
    visibility = normalize.clean_choice(draft.visibility or default_visibility,
                                       normalize.VISIBILITIES, default_visibility)
    db.execute(
        """INSERT INTO documents(
            id, user_id, kind, source, source_key, title, company, role, city,
            salary_text, salary_min, salary_max, experience, education, url,
            published_at, fetched_at, content_md, structured_json, visibility,
            license_note, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id, draft.user_id, kind, source, key,
            text_util.normalize_text(draft.title),
            text_util.normalize_text(draft.company),
            text_util.normalize_text(draft.role),
            normalize.normalize_city(draft.city),
            draft.salary_text, draft.salary_min, draft.salary_max,
            draft.experience, draft.education, draft.url,
            draft.published_at, now,
            text_util.normalize_text(draft.content_md),
            json.dumps(draft.structured, ensure_ascii=False),
            visibility, draft.license_note, now, now,
        ),
    )
    replace_chunks(db, doc_id, draft.user_id, draft.content_md)
    return doc_id, True


def replace_chunks(
    db: sqlite3.Connection, doc_id: str, user_id: str | None, content: object
) -> int:
    """重建某份资料的分块与检索索引，返回块数。"""
    stale = [row["id"] for row in db.execute(
        "SELECT id FROM knowledge_chunks WHERE doc_id = ?", (doc_id,)
    )]
    for chunk_id in stale:
        db.execute("DELETE FROM knowledge_fts WHERE chunk_id = ?", (chunk_id,))
    db.execute("DELETE FROM knowledge_chunks WHERE doc_id = ?", (doc_id,))

    pieces = split_chunks(content)
    for index, piece in enumerate(pieces):
        tokens = text_util.tokenize(piece)
        cursor = db.execute(
            """INSERT INTO knowledge_chunks(doc_id, user_id, chunk_index, text, text_tokens, tokens)
               VALUES(?,?,?,?,?,?)""",
            (doc_id, user_id, index, piece, " ".join(tokens), len(tokens)),
        )
        db.execute(
            "INSERT INTO knowledge_fts(text_tokens, chunk_id) VALUES(?,?)",
            (" ".join(tokens), cursor.lastrowid),
        )
    return len(pieces)


def search(
    db: sqlite3.Connection,
    query: object,
    *,
    user_id: str | None,
    scopes: Iterable[str] = ("private", "public"),
    kinds: Iterable[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """BM25 全文检索；返回命中块及其所属资料。"""
    match = text_util.match_query(query)
    if not match:
        return []

    scopes = set(scopes or ())
    owner = _owner(user_id)
    scope_sql = []
    params: list[Any] = [match]
    if "private" in scopes:
        scope_sql.append("COALESCE(d.user_id,'') = ?")
        params.append(owner)
    if "public" in scopes:
        scope_sql.append("d.visibility = 'public'")
    if not scope_sql:
        return []

    kinds = list(kinds or [])
    kind_sql = ""
    if kinds:
        kind_sql = f" AND d.kind IN ({','.join('?' for _ in kinds)})"
        params.extend(kinds)
    params.append(max(1, min(int(limit), 50)))

    sql = f"""
        SELECT c.id AS chunk_id, c.doc_id, c.chunk_index, c.text,
               d.title, d.company, d.role, d.kind, d.visibility,
               bm25(knowledge_fts) AS rank
        FROM knowledge_fts
        JOIN knowledge_chunks c ON c.id = knowledge_fts.chunk_id
        JOIN documents d ON d.id = c.doc_id
        WHERE knowledge_fts MATCH ?
          AND d.visibility != 'rejected'
          AND ({' OR '.join(scope_sql)}){kind_sql}
        ORDER BY rank
        LIMIT ?
    """
    rows = db.execute(sql, params).fetchall()
    return [
        {
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "title": row["title"],
            "company": row["company"],
            "role": row["role"],
            "kind": row["kind"],
            "visibility": row["visibility"],
            "excerpt": row["text"],
            "score": round(-float(row["rank"]), 6),
        }
        for row in rows
    ]


def set_visibility(
    db: sqlite3.Connection,
    doc_id: str,
    *,
    user_id: str,
    visibility: str,
    review_note: str = "",
    reviewed_by: str | None = None,
) -> bool:
    """提审/审核的资料状态切换；只有本人或管理员调用，越权由调用方拦截。"""
    visibility = normalize.clean_choice(visibility, normalize.VISIBILITIES, "private")
    now = time.time()
    cursor = db.execute(
        """UPDATE documents
              SET visibility = ?, review_note = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ? AND COALESCE(user_id,'') = ?""",
        (visibility, review_note, reviewed_by, now, now, doc_id, _owner(user_id)),
    )
    return cursor.rowcount > 0


def delete_document(db: sqlite3.Connection, doc_id: str, *, user_id: str) -> bool:
    """删除本人资料；分块随外键级联清理，检索索引需要显式清（FTS 表无外键）。"""
    chunk_ids = [row["id"] for row in db.execute(
        "SELECT id FROM knowledge_chunks WHERE doc_id = ?", (doc_id,)
    )]
    for chunk_id in chunk_ids:
        db.execute("DELETE FROM knowledge_fts WHERE chunk_id = ?", (chunk_id,))
    cursor = db.execute(
        "DELETE FROM documents WHERE id = ? AND COALESCE(user_id,'') = ?",
        (doc_id, _owner(user_id)),
    )
    return cursor.rowcount > 0
