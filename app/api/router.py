from fastapi import APIRouter
from app.api import admin, analysis, auth, diagrams, projects, tasks, uploads

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(uploads.router)
api_router.include_router(tasks.router)
api_router.include_router(analysis.router)
api_router.include_router(diagrams.router)
api_router.include_router(admin.router)
