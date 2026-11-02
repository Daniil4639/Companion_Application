"""MCP bearer secrets use the same OS-backed store policy as LLM keys."""
from backend.app.llm.credentials import CredentialStore


class MCPCredentialStore(CredentialStore):
    service = "Folliant.MCP"
