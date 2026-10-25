from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db import get_db
from backend.app.dto.user import UserCreate, UserPatch, UserResponse
from backend.app.services import user_service


user_router = APIRouter(prefix="/user", tags=["Local profile"])


@user_router.get("", response_model=UserResponse)
async def get_user(session: AsyncSession = Depends(get_db)):
    return await user_service.get_user(session)


@user_router.post("", response_model=UserResponse, status_code=201)
async def create_user(data: UserCreate, session: AsyncSession = Depends(get_db)):
    return await user_service.create_user(data, session)


@user_router.patch("", response_model=UserResponse)
async def update_user(data: UserPatch, session: AsyncSession = Depends(get_db)):
    return await user_service.update_user(data, session)
