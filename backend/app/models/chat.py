from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint, Index, text
from backend.app.db.base import Base
from backend.app.db.types import UTCDateTime
from backend.app.utils.time import utc_now


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1)
    title = Column(String(128), nullable=False)
    provider_id = Column(String(64), ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    model = Column(String(255), nullable=False)
    system_prompt = Column(Text, nullable=False, default="")
    context_window_tokens = Column(Integer, nullable=False)
    max_output_tokens = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime(), nullable=False, default=utc_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (UniqueConstraint("conversation_id", "position"),)
    id = Column(String(32), primary_key=True)
    conversation_id = Column(String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    text = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False)
    position = Column(Integer, nullable=False)
    provider_id = Column(String(64), nullable=True)
    model = Column(String(255), nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, default=utc_now)


class GenerationRun(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id"),
        Index("uq_chat_active_run", "conversation_id", unique=True,
              sqlite_where=text("status IN ('pending','running')")),
    )
    id = Column(String(32), primary_key=True)
    conversation_id = Column(String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    request_id = Column(String(64), nullable=False)
    user_message_id = Column(String(32), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    assistant_message_id = Column(String(32), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    finished_at = Column(UTCDateTime(), nullable=True)