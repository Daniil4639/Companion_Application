from backend.app.models.user import User
from backend.app.dto.user import UserCreate, UserPatch
from backend.app.db.session import write_transaction
from backend.app.utils.time import utc_now


class UserNotFound(Exception):
    pass


class UserExists(Exception):
    pass


async def find_user(session):
    return await session.get(User, 1)


async def get_time_context(session):
    """Only public time settings; system mode uses the browser's last saved IANA zone."""
    from backend.app.dto.recurrence_editing import UserTimeContext
    from backend.app.utils.time import zone
    user = await find_user(session)
    timezone = user.timezone if user else "UTC"
    now = utc_now()
    local = now.astimezone(zone(timezone))
    warnings = []
    if user is None:
        warnings.append("No profile exists; UTC fallback is used")
    elif user.timezone_mode == "system":
        warnings.append(
            "System timezone is the browser's last saved value; MCP cannot inspect the current client OS timezone")
    return UserTimeContext(now_utc=now, local_datetime=local, local_date=local.date(), timezone=timezone,
                           timezone_mode=user.timezone_mode if user else None,
                           timezone_source="saved_profile" if user else "utc_fallback",
                           locale=user.locale if user else "ru-RU", warnings=warnings)


async def get_user(session):
    user = await find_user(session)
    if user is None:
        raise UserNotFound("Профиль ещё не создан")
    return user


async def create_user(data: UserCreate, session):
    # Shared reservation also serializes concurrent first-launch requests.
    async with write_transaction(session):
        if await find_user(session) is not None:
            raise UserExists("Профиль уже существует")

        user = User(id=1, **data.model_dump())
        session.add(user)
        await session.flush()

    return user


async def update_user(data: UserPatch, session):
    async with write_transaction(session):
        user = await get_user(session)

        merged = UserCreate.model_validate({
            **{key: getattr(user, key) for key in UserCreate.model_fields},
            **data.model_dump(exclude_unset=True),
        })

        for key, value in merged.model_dump().items():
            setattr(user, key, value)
        user.updated_at = utc_now()
        await session.flush()

    return user