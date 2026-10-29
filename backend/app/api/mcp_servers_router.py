from fastapi import APIRouter, Depends, Request, Response, HTTPException
from backend.app.dto.mcp_servers import MCPServerCreate, MCPServerPatch, MCPServerResponse, MCPConnectionStatus
from backend.app.mcp_client.models import RegisteredTool


def catalog(request: Request):
    from backend.app.mcp_adapter.security import local_request_allowed
    if not local_request_allowed(request.scope):
        raise HTTPException(403, "MCP settings accept direct localhost connections only")
    return request.app.state.mcp_catalog


mcp_servers_router = APIRouter(prefix="/api/mcp/servers", tags=["MCP connections"])


@mcp_servers_router.get("", response_model=list[MCPServerResponse])
async def list_servers(service=Depends(catalog)):
    return await service.read_all()


@mcp_servers_router.post("", response_model=MCPServerResponse, status_code=201)
async def create_server(data: MCPServerCreate, service=Depends(catalog)):
    return await service.create(data)


@mcp_servers_router.get("/{server_id}", response_model=MCPServerResponse)
async def get_server(server_id: str, service=Depends(catalog)):
    return await service.get(server_id)


@mcp_servers_router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_server(server_id: str, data: MCPServerPatch, service=Depends(catalog)):
    return await service.update(server_id, data)


@mcp_servers_router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: str, service=Depends(catalog)):
    await service.delete(server_id)
    return Response(status_code=204)


@mcp_servers_router.get("/{server_id}/status", response_model=MCPConnectionStatus)
async def server_status(server_id: str, service=Depends(catalog)):
    await service.get(server_id)
    return service.manager.status(server_id)


@mcp_servers_router.get("/{server_id}/tools", response_model=list[RegisteredTool])
async def cached_tools(server_id: str, service=Depends(catalog)):
    await service.get(server_id)
    return service.manager.registry.list(server_id)


@mcp_servers_router.post("/{server_id}/test", response_model=MCPConnectionStatus)
async def test_connection(server_id: str, service=Depends(catalog)):
    await service.get(server_id)
    # A real protocol request also probes an already-open connection.
    await service.manager.refresh_tools(server_id)
    return service.manager.status(server_id)


@mcp_servers_router.post("/{server_id}/refresh-tools", response_model=list[RegisteredTool])
async def refresh_tools(server_id: str, service=Depends(catalog)):
    await service.get(server_id)
    return await service.manager.refresh_tools(server_id)