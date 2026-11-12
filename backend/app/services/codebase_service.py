"""Lightweight codebase storage with branches and commits (not full Git)."""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId

from .. import db
from ..config import settings


def _project_code_dir(project_id: str) -> Path:
    p = Path(settings.projects_dir) / project_id / "codebase"
    p.mkdir(parents=True, exist_ok=True)
    (p / "working").mkdir(exist_ok=True)
    (p / "versions").mkdir(exist_ok=True)
    return p


def _serialize(doc: dict) -> dict:
    if not doc:
        return doc
    out = {**doc}
    out["id"] = str(out.pop("_id"))
    for k, v in list(out.items()):
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, list) and v and isinstance(v[0], ObjectId):
            out[k] = [str(x) for x in v]
    return out


def _hash_tree(root: Path) -> str:
    """Simple content-addressed tree hash."""
    h = hashlib.sha256()
    if not root.exists():
        return h.hexdigest()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(root)).replace("\\", "/")
            h.update(rel.encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if src.exists():
        shutil.copytree(src, dst)


async def list_branches(project_id: str) -> list[dict]:
    cursor = db.code_branches.find({"project_id": ObjectId(project_id)}).sort("name", 1)
    return [_serialize(d) async for d in cursor]


async def create_branch(project_id: str, name: str, from_branch: str = "main") -> dict:
    now = datetime.now(timezone.utc)
    parent = await db.code_branches.find_one({
        "project_id": ObjectId(project_id),
        "name": from_branch,
    })
    head = parent.get("head_commit_id") if parent else None
    doc = {
        "project_id": ObjectId(project_id),
        "name": name.strip(),
        "head_commit_id": head,
        "is_default": False,
        "created_at": now,
    }
    res = await db.code_branches.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _serialize(doc)


def get_working_tree(project_id: str, path: str = "") -> list[dict]:
    """Return directory listing of the working tree (or a subpath)."""
    root = _project_code_dir(project_id) / "working"
    target = (root / path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("Invalid path")
    if not target.exists():
        return []
    items = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        items.append({
            "name": child.name,
            "path": str(child.relative_to(root)).replace("\\", "/"),
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return items


def read_file(project_id: str, path: str, ref: str | None = None) -> dict:
    """Read a file from working tree or a version snapshot."""
    code_dir = _project_code_dir(project_id)
    if ref and ref != "working":
        base = code_dir / "versions" / ref
    else:
        base = code_dir / "working"
    target = (base / path).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise ValueError("Invalid path")
    if not target.is_file():
        raise FileNotFoundError(path)
    data = target.read_bytes()
    try:
        text = data.decode("utf-8")
        return {"path": path, "content": text, "encoding": "utf-8", "size": len(data)}
    except UnicodeDecodeError:
        return {"path": path, "content": None, "encoding": "binary", "size": len(data)}


async def import_files(project_id: str, files: list[tuple[str, bytes]]) -> dict:
    """Write files into the working tree. files = [(relative_path, content_bytes), ...]"""
    working = _project_code_dir(project_id) / "working"
    written = 0
    for rel, content in files:
        rel = rel.lstrip("/").replace("\\", "/")
        if ".." in rel:
            continue
        dest = working / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        written += 1
    return {"written": written, "tree_hash": _hash_tree(working)}


async def create_commit(
    project_id: str,
    branch: str,
    message: str,
    author: str = "user",
) -> dict:
    now = datetime.now(timezone.utc)
    code_dir = _project_code_dir(project_id)
    working = code_dir / "working"
    tree_hash = _hash_tree(working)

    branch_doc = await db.code_branches.find_one({
        "project_id": ObjectId(project_id),
        "name": branch,
    })
    parent_ids = []
    if branch_doc and branch_doc.get("head_commit_id"):
        parent_ids = [branch_doc["head_commit_id"]]

    commit = {
        "project_id": ObjectId(project_id),
        "branch": branch,
        "message": message.strip() or "Update",
        "parent_ids": parent_ids,
        "tree_hash": tree_hash,
        "author": author,
        "created_at": now,
        "stats": {"files_changed": 0, "additions": 0, "deletions": 0},
    }
    res = await db.code_commits.insert_one(commit)
    commit_id = res.inserted_id
    commit["_id"] = commit_id

    snapshot = code_dir / "versions" / str(commit_id)
    _copy_tree(working, snapshot)

    await db.code_branches.update_one(
        {"project_id": ObjectId(project_id), "name": branch},
        {"$set": {"head_commit_id": commit_id}},
        upsert=True,
    )
    return _serialize(commit)


async def list_commits(project_id: str, branch: str | None = None, limit: int = 50) -> list[dict]:
    q: dict[str, Any] = {"project_id": ObjectId(project_id)}
    if branch:
        q["branch"] = branch
    cursor = db.code_commits.find(q).sort("created_at", -1).limit(limit)
    return [_serialize(d) async for d in cursor]


async def get_commit(project_id: str, commit_id: str) -> dict | None:
    doc = await db.code_commits.find_one({
        "_id": ObjectId(commit_id),
        "project_id": ObjectId(project_id),
    })
    return _serialize(doc) if doc else None


def simple_diff(project_id: str, from_ref: str, to_ref: str = "working") -> list[dict]:
    """Path-level diff between two snapshots. from_ref/to_ref can be commit ids or 'working'."""
    code_dir = _project_code_dir(project_id)

    def base_for(ref: str) -> Path:
        if ref == "working":
            return code_dir / "working"
        return code_dir / "versions" / ref

    a = base_for(from_ref)
    b = base_for(to_ref)
    if not a.exists() or not b.exists():
        return []

    def all_files(root: Path) -> dict[str, str]:
        out = {}
        if not root.exists():
            return out
        for p in root.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(root)).replace("\\", "/")
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return out

    fa, fb = all_files(a), all_files(b)
    changes = []
    for path in sorted(set(fa) | set(fb)):
        if path not in fa:
            changes.append({"path": path, "status": "added"})
        elif path not in fb:
            changes.append({"path": path, "status": "deleted"})
        elif fa[path] != fb[path]:
            changes.append({"path": path, "status": "modified"})
    return changes
