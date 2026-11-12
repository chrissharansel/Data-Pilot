from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import project_store

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_branch: str | None = None


@router.post("")
async def create_project(body: ProjectCreate):
    return await project_store.create_project(body.name, body.description)


@router.get("")
async def list_projects():
    return await project_store.list_projects()


@router.get("/{project_id}")
async def get_project(project_id: str):
    proj = await project_store.get_project(project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@router.patch("/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    proj = await project_store.update_project(
        project_id,
        name=body.name,
        description=body.description,
        default_branch=body.default_branch,
    )
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    ok = await project_store.delete_project(project_id)
    if not ok:
        raise HTTPException(404, "Project not found")
    return {"ok": True}
