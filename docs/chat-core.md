# Chat Core

Local chat uses one FastAPI worker. Conversations and messages remain in SQLite even when a provider is removed. A conversation's provider reference becomes null; choose a new connection to resume.

## Configuration

Set FOLLIANT_SYSTEM_PROMPT in the application's environment to change the global instructions. The conversation prompt supplements them. The global prompt is read at application startup and is not copied to conversation records.

Run normal application startup to apply Alembic revision a6b9201d4e33. The migration adds conversations, chat_messages and generation_runs; it does not alter calendar or MCP tables.

## Generation

POST /api/chats/{id}/messages accepts text and request_id. Reuse the same request_id when retrying an uncertain submission. A unique partial index prevents concurrent active runs in a conversation. The process owns the producer task; closing SSE does not cancel generation.

GET /api/chats/runs/{id}/events sends snapshot/progress/completed SSE events containing the full current text and status. Clients replace the displayed text, rather than concatenate it. This permits reconnecting without replay duplication. POST /api/chats/runs/{id}/cancel stops a run.

Partial text is checkpointed every three seconds. On graceful shutdown runs become interrupted and partial text is saved. On startup unfinished persisted runs are marked interrupted. An abrupt process termination can lose the last checkpoint interval.

History and chat lists are paginated. Failed/cancelled/interrupted exchanges stay visible but are excluded from subsequent model context.

## Context

ContextBuilder retains the global and local instructions and current input, then adds recent complete user/assistant pairs. It reserves max_output_tokens plus 256 tokens for protocol overhead. TokenCounter uses UTF-8 byte length plus message overhead as a conservative estimate, not an exact tokenizer. This can retain substantially less history than a model-specific tokenizer.

Ollama receives num_ctx from the chat setting. Its model-info endpoint exposes the model's declared context length when available; this does not prove the effective server configuration. OpenAI's standard model metadata does not provide context-window size, so the UI permits manual configuration. For Unsloth Studio enter the actually configured context, which can be smaller than the model's published maximum.

## UI

The chat has a conversation list, an empty upper area reserved for the future mascot, and the message area below. Provider lists come from saved LLM connections. Model discovery may fail without preventing manual model entry.

Markdown rendering supports bold, inline code and fenced code with lightweight keyword/string/number highlighting. All content is escaped first; raw HTML and remote images are not rendered.

No real LLM is called by the mock tests:
python -m unittest discover -s tests -p test_chat.py -v
python -m unittest discover -s tests -p test_llm.py -q

There is no AgentRunner, MCP execution, attachment handling or tool calling in this iteration.

