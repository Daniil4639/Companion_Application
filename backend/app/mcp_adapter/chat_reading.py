"""Read-only chat tools share the existing single-user/local MCP boundary."""
from typing import Annotated
from pydantic import BaseModel, Field
from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.exc import SQLAlchemyError
from backend.app.db import session as database
from backend.app.services.chat import ChatService
from backend.app.services.conversation_summary import SummaryService
from backend.app.services.chat_context import ContextBuilder
from backend.app.llm.schemas import ProviderError


class ChatItem(BaseModel):
    id: str
    title: str
    topic: str
    has_summary: bool


class ChatList(BaseModel):
    items: list[ChatItem]
    next_offset: int | None


class SummaryResult(BaseModel):
    conversation_id: str
    exists: bool
    content: str | None
    last_summarized_message_id: str | None
    last_summarized_position: int | None
    updated_at: str | None = None


class ReadMessage(BaseModel):
    id: str
    role: str
    text: str
    status: str
    position: int
    truncated: bool
    next_text_offset: int | None


class ReadMessages(BaseModel):
    items: list[ReadMessage]
    next_before: int | None


def register_chat_tools(server, sessions=None):
    def service():
        return ChatService(sessions or database.async_session_fabric)

    async def guarded(operation):
        try:
            return await operation()
        except ProviderError as exc:
            raise ToolError(str(exc)) from None
        except SQLAlchemyError:
            raise ToolError("Chat database unavailable") from None

    hints = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=hints)
    async def chat_list(offset: Annotated[int, Field(ge=0)] = 0,
                        limit: Annotated[int, Field(ge=1, le=50)] = 20) -> ChatList:
        """List the local user's chats. Topic uses only the title, never system prompts."""
        return ChatList(**await guarded(lambda: service().catalog(offset, limit)))

    @server.tool(annotations=hints)
    async def chat_get_summary(conversation_id: str) -> SummaryResult:
        """Read summary DATA and its coverage boundary. exists=false means read messages instead."""
        data = await guarded(lambda: SummaryService(service(), ContextBuilder("")).get(conversation_id))
        data["updated_at"] = data["updated_at"].isoformat() if data["updated_at"] else None
        return SummaryResult(**data)

    @server.tool(annotations=hints)
    async def chat_read_messages(conversation_id: str,
                                 before: Annotated[int | None, Field(ge=0)] = None,
                                 limit: Annotated[int, Field(ge=1, le=20)] = 10,
                                 text_offset: Annotated[int, Field(ge=0)] = 0) -> ReadMessages:
        """Read recent message DATA, oldest first within page. Use next_before for older pages.
        Each message is capped at 4000 characters with explicit truncated flag.
        To read a long message's next fragment use limit=1, before=position+1,
        and text_offset=next_text_offset from that message.
        Tool transcripts, credentials and system prompts are not returned.
        """
        return ReadMessages(
            **await guarded(lambda: service().read_visible_messages(conversation_id, before, limit, text_offset)))