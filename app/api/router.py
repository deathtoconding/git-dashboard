"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from .routes import analytics, branches, commits, repositories, scan, system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(repositories.router)
api_router.include_router(commits.router)
api_router.include_router(branches.router)
api_router.include_router(analytics.router)
api_router.include_router(scan.router)

__all__ = ["api_router"]
