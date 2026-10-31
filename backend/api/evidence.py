"""账户内的事实卡片、保守查重和可恢复导入。"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from api.workspace import ProfileState, encode_record, timestamp, check_account
from core import accounts

router = APIRouter(prefix="/api/library", tags=["library"], dependencies=[Depends(accounts.require_csrf)])
FIELDS = ("kind", "name", "role", "period", "actions", "results", "skills")
LISTS = ("actions", "results", "skills")

def norm(value):
    # Keep digits and mathematical symbols: a cosmetic match must not erase a sign or unit.
    return re.sub(r"[\s，,。；;：:、]+", "", unicodedata.normalize("NFKC", str(value)).casefold())

def fact(value):
    result = {key: copy.deepcopy(value.get(key, [] if key in LISTS else "")) for key in FIELDS}
    for key in LISTS:
        result[key] = list(dict.fromkeys(s.strip() for s in result[key] if s.strip()))
    if result["kind"] == "education":
        for key in LISTS:
            result[key] = []
    return result

def same(left, right):
    return all(({norm(x) for x in left[k]} == {norm(x) for x in right[k]}) if k in LISTS else norm(left[k]) == norm(right[k]) for k in FIELDS)

def covered(incoming, existing):
    return all(({norm(x) for x in incoming[k]} <= {norm(x) for x in existing[k]}) if k in LISTS else (not incoming[k] or norm(incoming[k]) == norm(existing[k])) for k in FIELDS)

def number_conflict(old, new):
    # Same claim with a changed numerical literal is a conflict, not new evidence.
    def skeleton(value):
        return re.sub(r"[0-9]+(?:[.][0-9]+)?", "#", norm(value))
    return any(skeleton(a) == skeleton(b) and norm(a) != norm(b) and re.search(r"[0-9]", a) and re.search(r"[0-9]", b) for a in old for b in new)

def load_bank(db, uid):
    row = db.execute("SELECT revision,state_json FROM evidence_banks WHERE user_id=?", (uid,)).fetchone()
    return (row["revision"], json.loads(row["state_json"])) if row else (0, {"cards": [], "sources": [], "migrated": []})

def persist(db, uid, revision, bank):
    encoded = encode_record(bank, 32 * 1024 * 1024)
    db.execute("INSERT INTO evidence_banks(user_id,revision,state_json) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,state_json=excluded.state_json", (uid, revision + 1, encoded))

def record(card):
    card["history"].append({"at": timestamp(), "facts": fact(card), "deleted": card["deleted"], "source_ids": list(card["source_ids"])})

class Material(BaseModel):
    expected_user_id: str
    profile: ProfileState | None = None
    legacy_id: str | None = None
    source_name: str = Field(default="上传材料", max_length=200)

class Choice(BaseModel):
    action: Literal["skip", "new", "merge"] = "skip"
    target: str | None = None
    # Every changed field requires its own explicit selection.
    fields: list[str] = Field(default_factory=list)
    replace_fields: list[str] = Field(default_factory=list)

class ImportRequest(Material):
    revision: int = Field(ge=0)
    facts_confirmed: bool = False
    choices: list[Choice]

class CardAction(BaseModel):
    expected_user_id: str
    revision: int = Field(ge=0)
    action: Literal["delete", "restore", "revert"]
    version: int | None = None

def material(db, req, uid):
    if (req.profile is None) == (req.legacy_id is None):
        raise HTTPException(422, "请选择一份材料")
    if req.legacy_id:
        row = db.execute("SELECT profile_json FROM profiles WHERE id=? AND user_id=?", (req.legacy_id, uid)).fetchone()
        if row is None:
            raise HTTPException(404, "历史材料不存在")
        profile = ProfileState.model_validate(json.loads(row["profile_json"]))
    else:
        profile = req.profile
    data = profile.model_dump()
    encode_record(data, 2 * 1024 * 1024)
    return data

def proposals(bank, profile):
    cards = [c for c in bank["cards"] if not c["deleted"]]
    items = []
    for value in profile["experiences"]:
        incoming = fact(value)
        candidates = []
        for card in cards:
            if card["kind"] != incoming["kind"]:
                continue
            score = SequenceMatcher(None, norm(card["name"]), norm(incoming["name"])).ratio()
            content_score = SequenceMatcher(None, norm(" ".join(incoming["actions"] + incoming["results"])), norm(" ".join(card["actions"] + card["results"]))).ratio() if incoming["actions"] or incoming["results"] else 0
            likely = covered(incoming, card) or score >= .45 or content_score >= .65 or bool(incoming["period"] and norm(incoming["period"]) == norm(card["period"]) and incoming["role"] and norm(incoming["role"]) == norm(card["role"]))
            candidates.append({"id": card["id"], "facts": fact(card), "same": covered(incoming, card), "score": score, "likely": likely, "conflicts": [k for k in LISTS if number_conflict(card[k], incoming[k])]})
        candidates.sort(key=lambda c: (c["same"], c["score"]), reverse=True)
        items.append({"incoming": incoming, "status": "same" if any(c["same"] for c in candidates) else "review" if any(c["likely"] for c in candidates) else "new", "candidates": candidates})
    return items

@router.get("")
def listing(user: dict = Depends(accounts.require_user)):
    with accounts.connection() as db:
        revision, bank = load_bank(db, user["id"])
        legacy = [dict(r) for r in db.execute("SELECT id,name,saved_at FROM profiles WHERE user_id=? ORDER BY rowid DESC", (user["id"],))]
    return {"ok": True, "revision": revision, **bank, "legacy": legacy}

@router.post("/preview")
def preview(req: Material, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    with accounts.connection() as db:
        revision, bank = load_bank(db, user["id"])
        profile = material(db, req, user["id"])
    return {"ok": True, "revision": revision, "items": proposals(bank, profile), "education_notes": profile["education"], "profile": profile}

@router.post("/import")
def apply(req: ImportRequest, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    with accounts.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        revision, bank = load_bank(db, user["id"])
        if revision != req.revision:
            raise HTTPException(409, "经历库已变化，请重新查重")
        profile = material(db, req, user["id"])
        if not req.facts_confirmed or (not req.legacy_id and not profile["user_confirmed"]):
            raise HTTPException(422, "请先核对并确认材料事实")
        if len(req.choices) != len(profile["experiences"]):
            raise HTTPException(422, "请逐项确认导入方式")
        source_id = uuid4().hex
        changes = 0
        for value, choice in zip(profile["experiences"], req.choices):
            incoming = fact(value)
            if choice.action == "skip":
                continue
            if not incoming["name"].strip():
                raise HTTPException(422, "经历名称不能为空")
            if any(k not in FIELDS or k == "kind" for k in choice.fields) or any(k not in LISTS or k not in choice.fields for k in choice.replace_fields):
                raise HTTPException(422, "不支持的事实字段")
            # Recheck against earlier items of this same batch and restored cards.
            duplicate = next((c for c in bank["cards"] if not c["deleted"] and covered(incoming, c)), None)
            if duplicate:
                continue
            if choice.action == "new":
                card = {**incoming, "id": uuid4().hex, "deleted": False, "source_ids": [source_id], "history": []}
                bank["cards"].append(card)
            else:
                card = next((c for c in bank["cards"] if c["id"] == choice.target and not c["deleted"]), None)
                if card is None or card["kind"] != incoming["kind"]:
                    raise HTTPException(422, "请选择当前账户内同类别的卡片")
                before = fact(card)
                for key in choice.fields:
                    # Append only explicitly selected information. Replacement is a separate explicit choice.
                    if key in LISTS and key not in choice.replace_fields:
                        if number_conflict(card[key], incoming[key]):
                            raise HTTPException(422, "数字存在差异，请明确保留原有字段或采用新材料替换，不可作为新增条目追加")
                        seen = {norm(x) for x in card[key]}
                        card[key] += [x for x in incoming[key] if norm(x) not in seen]
                    else:
                        card[key] = incoming[key]
                if same(before, card):
                    continue
                card["source_ids"].append(source_id)
            record(card)
            changes += 1
        if changes:
            bank["sources"].append({"id": source_id, "name": req.source_name, "at": timestamp(), "profile": profile, "legacy_id": req.legacy_id})
        migrated = bool(req.legacy_id and req.legacy_id not in bank["migrated"])
        if migrated:
            bank["migrated"].append(req.legacy_id)
        if changes or migrated:
            persist(db, user["id"], revision, bank)
        return {"ok": True, "changed": changes, "revision": revision + int(bool(changes or migrated))}

@router.post("/{card_id}/action")
def action(card_id: str, req: CardAction, user: dict = Depends(accounts.require_user)):
    check_account(req.expected_user_id, user)
    with accounts.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        revision, bank = load_bank(db, user["id"])
        if req.revision != revision:
            raise HTTPException(409, "经历库已变化，请刷新后重试")
        card = next((c for c in bank["cards"] if c["id"] == card_id), None)
        if card is None:
            raise HTTPException(404, "卡片不存在")
        if req.action == "revert":
            if req.version is None or req.version < 0 or req.version >= len(card["history"]):
                raise HTTPException(422, "版本不存在")
            previous = copy.deepcopy(card["history"][req.version])
            card.update(previous["facts"])
            card["source_ids"] = list(dict.fromkeys(card["source_ids"] + previous["source_ids"]))
        else:
            card["deleted"] = req.action == "delete"
        if not card["deleted"] and any(c["id"] != card_id and not c["deleted"] and same(c, card) for c in bank["cards"]):
            raise HTTPException(409, "已有相同卡片，未恢复重复内容")
        record(card)
        persist(db, user["id"], revision, bank)
    return {"ok": True, "revision": revision + 1}
