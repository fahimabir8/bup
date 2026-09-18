from fastapi import FastAPI
from app.api.main import api_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
