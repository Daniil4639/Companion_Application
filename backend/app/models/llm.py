from sqlalchemy import Column, String, Float, Integer, ForeignKey, CheckConstraint
from backend.app.db.base import Base


class LLMProviderRecord(Base):
    __tablename__ = "llm_providers"
    __table_args__ = (CheckConstraint("kind IN ('openai','ollama')", name="ck_llm_kind"),)
    id = Column(String(64), primary_key=True)
    kind = Column(String(16), nullable=False)
    name = Column(String(128), nullable=False)
    base_url = Column(String(2048), nullable=False)
    timeout = Column(Float, nullable=False)
    connect_timeout = Column(Float, nullable=False)
    secret_ref = Column(String(32), nullable=True)


class LLMSelectionRecord(Base):
    __tablename__ = "llm_selection"
    __table_args__ = (CheckConstraint("id = 1", name="ck_llm_selection_singleton"),)
    id = Column(Integer, primary_key=True, autoincrement=False)
    provider_id = Column(String(64), ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False)
    model = Column(String(255), nullable=False)
    temperature = Column(Float, nullable=True)
    max_output_tokens = Column(Integer, nullable=True)