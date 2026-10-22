from fastapi import APIRouter


health_check_router = APIRouter(prefix="/api/health", tags=["Health check"])


@health_check_router.get(path="")
async def health_check():
    return {"status": "ok"}