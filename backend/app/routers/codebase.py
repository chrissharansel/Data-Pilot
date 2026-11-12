from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..services import codebase_service

router = APIRouter(prefix="/api/projects/{project_id}/code", tags=["codebase"])


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    from_branch: str = "main"


class CommitCreate(BaseModel):
    message: str = Field(..., min_length=1)
    branch: str = "main"
    author: str = "user"


@router.get("/tree")
async def get_tree(project_id: str, path: str = ""):
    try:
        return codebase_service.get_working_tree(project_id, path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/file")
async def read_file(project_id: str, path: str, ref: str | None = None):
    try:
        return codebase_service.read_file(project_id, path, ref)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/upload")
async def upload_files(
    project_id: str,
    files: list[UploadFile] = File(...),
    paths: list[str] | None = Form(None),
):
    pairs: list[tuple[str, bytes]] = []
    for i, f in enumerate(files):
        rel = (paths[i] if paths and i < len(paths) else f.filename) or f"file_{i}"
        content = await f.read()
        pairs.append((rel, content))
    result = await codebase_service.import_files(project_id, pairs)
    return result


@router.get("/branches")
async def list_branches(project_id: str):
    return await codebase_service.list_branches(project_id)


@router.post("/branches")
async def create_branch(project_id: str, body: BranchCreate):
    return await codebase_service.create_branch(project_id, body.name, body.from_branch)


@router.get("/commits")
async def list_commits(project_id: str, branch: str | None = None, limit: int = 50):
    return await codebase_service.list_commits(project_id, branch, limit)


@router.post("/commits")
async def create_commit(project_id: str, body: CommitCreate):
    return await codebase_service.create_commit(
        project_id, branch=body.branch, message=body.message, author=body.author
    )


@router.get("/commits/{commit_id}")
async def get_commit(project_id: str, commit_id: str):
    c = await codebase_service.get_commit(project_id, commit_id)
    if not c:
        raise HTTPException(404, "Commit not found")
    return c


@router.get("/diff")
async def get_diff(project_id: str, from_ref: str, to_ref: str = "working"):
    return codebase_service.simple_diff(project_id, from_ref, to_ref)
