import asyncio
import json
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse, Response
from backend.app.dto.chat import ChatSettings, SendMessage, ToolDecision
from backend.app.mcp_adapter.security import local_request_allowed
from backend.app.services.chat import ACTIVE


def services(request: Request):
    if not local_request_allowed(request.scope):
        raise HTTPException(403, "Chat accepts direct localhost connections only")
    return request.app.state.chat_service, request.app.state.chat_generations


chat_router = APIRouter(prefix="/api/chats", tags=["Chat"])


@chat_router.get("")
async def listing(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), pair=Depends(services)):
    return await pair[0].list(offset, limit)


@chat_router.post("", status_code=201)
async def create(data: ChatSettings, pair=Depends(services)):
    return await pair[0].save(data)


@chat_router.get("/runs/{run_id}")
async def run(run_id: str, pair=Depends(services)):
    return await pair[1].snapshot(run_id)


@chat_router.get("/provider-availability")
async def availability(pair=Depends(services)):
    return await pair[0].busy_providers()


@chat_router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, pair=Depends(services)):
    return await pair[1].cancel(run_id)


@chat_router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request, pair=Depends(services)):
    await pair[1].snapshot(run_id)

    async def stream():
        previous = None
        while not await request.is_disconnected():
            current = await pair[1].snapshot(run_id)
            payload = json.dumps(jsonable_encoder(current), ensure_ascii=False)
            if payload != previous:
                event = "snapshot" if previous is None else "completed" if current[
                                                                               "status"] not in ACTIVE else "progress"
                yield f"event: {event}\ndata: {payload}\n\n"
                previous = payload
            else:
                yield ": keepalive\n\n"
            if current["status"] not in ACTIVE:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@chat_router.post("/runs/{run_id}/tools/{tool_id}/decision")
async def decision(run_id: str, tool_id: str, data: ToolDecision, pair=Depends(services)):
    if not pair[1].agent:
        raise HTTPException(503, "Agent unavailable")
    return await pair[1].agent.store.decision(run_id, tool_id, data.approve)


@chat_router.get("/{id}")
async def get(id: str, pair=Depends(services)):
    return await pair[0].get(id)


@chat_router.put("/{id}")
async def save(id: str, data: ChatSettings, pair=Depends(services)):
    return await pair[0].save(data, id)


@chat_router.delete("/{id}", status_code=204)
async def delete(id: str, pair=Depends(services)):
    await pair[0].delete(id)
    return Response(status_code=204)


@chat_router.get("/{id}/messages")
async def messages(id: str, before: int | None = Query(None, ge=0), limit: int = Query(50, ge=1, le=100),
                   pair=Depends(services)):
    return await pair[0].messages(id, before, limit)


@chat_router.get("/{id}/run")
async def latest(id: str, pair=Depends(services)):
    return await pair[0].latest_run(id)


@chat_router.post("/{id}/messages", status_code=202)
async def send(id: str, data: SendMessage, pair=Depends(services)):
    return await pair[1].start(id, data)