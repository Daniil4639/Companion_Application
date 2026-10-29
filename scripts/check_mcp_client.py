"""Run from project root: python -m scripts.check_mcp_client (server already running)."""
import asyncio
import json
import sys

from backend.app.db.session import async_session_fabric, engine
from backend.app.services.mcp_servers import MCPServerService
from sqlalchemy.exc import SQLAlchemyError
from backend.app.mcp_client.manager import MCPClientManager
from backend.app.mcp_client.executor import ToolExecutor
from backend.app.mcp_client.models import RuntimeFailure


async def main():
    try:
        records = await MCPServerService(async_session_fabric).read_all()
        manager = MCPClientManager([record.connection_config() for record in records])

    except (ValueError, SQLAlchemyError):
        await engine.dispose()
        print("Cannot read the MCP catalog. Start Folliant first and check DATABASE_URL.", file=sys.stderr)
        return 1

    try:
        tools = await manager.refresh_tools("folliant")
        print("Available tools:")

        for tool in tools:
            print(" -", tool.id)
        result = await ToolExecutor(manager).execute("folliant.tasks_list", {})

        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0 if result.status == "success" else 1

    except RuntimeFailure as exc:
        print(f"MCP diagnostic failed ({exc.kind}): {exc}", file=sys.stderr)
        return 1

    finally:
        await manager.aclose()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))