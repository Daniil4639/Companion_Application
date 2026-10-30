from fastapi import APIRouter, Depends, HTTPException, Request, Response
from backend.app.dto.llm import ProviderCreate, ProviderPatch, ProviderView
from backend.app.llm.schemas import ModelSelection, ModelInfo
from backend.app.mcp_adapter.security import local_request_allowed


def service(request: Request):
    if not local_request_allowed(request.scope):
        raise HTTPException(403, "LLM settings accept direct localhost connections only")
    return request.app.state.llm_providers


llm_router = APIRouter(prefix="/api/llm", tags=["LLM settings"])


@llm_router.get("/providers", response_model=list[ProviderView])
async def providers(s=Depends(service)):
    return await s.read_all()


@llm_router.post("/providers", response_model=ProviderView, status_code=201)
async def create(data: ProviderCreate, s=Depends(service)):
    return await s.save(data)


@llm_router.get("/providers/{provider_id}", response_model=ProviderView)
async def get(provider_id: str, s=Depends(service)):
    return await s.get(provider_id)


@llm_router.patch("/providers/{provider_id}", response_model=ProviderView)
async def update(provider_id: str, data: ProviderPatch, s=Depends(service)):
    return await s.save(data, provider_id)


@llm_router.delete("/providers/{provider_id}", status_code=204)
async def delete(provider_id: str, s=Depends(service)):
    await s.delete(provider_id)
    return Response(status_code=204)


@llm_router.get("/providers/{provider_id}/models", response_model=list[ModelInfo])
async def models(provider_id: str, s=Depends(service)):
    async with s.provider(provider_id) as provider:
        return await provider.list_models()


@llm_router.post("/providers/{provider_id}/check", response_model=list[ModelInfo])
async def check(provider_id: str, s=Depends(service)):
    async with s.provider(provider_id) as provider:
        return await provider.check()


@llm_router.get("/active", response_model=ModelSelection | None)
async def active(s=Depends(service)):
    return await s.active()


@llm_router.get("/providers/{provider_id}/model-info", response_model=ModelInfo)
async def model_info(provider_id: str, model: str, s=Depends(service)):
    async with s.provider(provider_id) as provider:
        if hasattr(provider, "model_info"):
            return await provider.model_info(model)
        return ModelInfo(id=model)


@llm_router.put("/active", response_model=ModelSelection)
async def select(data: ModelSelection, s=Depends(service)):
    return await s.select(data)