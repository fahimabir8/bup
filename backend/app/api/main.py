from fastapi import APIRouter
from app.api.routes import health, optimize

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(optimize.router, prefix="/optimize-energy", tags=["optimize"])
