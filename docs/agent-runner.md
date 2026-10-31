# AgentRunner

The existing GenerationManager owns a bounded AgentRunner. Runs keep status running while phase changes between generating, waiting_approval and tool_running. This preserves the existing unique active-run index and SSE contract. Snapshots include persisted tool executions; reconnecting does not execute or approve anything.

## Usage

Open chat settings and select MCP connections. Existing chats default to no MCP connections. The model receives tools only from selected connections. A failed discovery leaves ordinary text chat available. Tool aliases are stable hashes of server ID and original tool name.

Write/unknown tools show a confirmation card with server, name and arguments. Approval applies only to that stored execution. Arguments cannot be edited through the approval endpoint. A rejected call returns permission_denied to the model.

FOLLIANT_TRUSTED_READ_SERVERS is a comma-separated list, default folliant. Only these servers' explicit readOnlyHint=true and non-destructive tools run without approval. External annotations alone are not trusted. Configure this list only for servers whose declarations you trust. Annotation trust does not bypass MCP server access controls or executor JSON Schema validation.

Calls are serialized. Transport/protocol uncertainty terminates the run with unknown outcome; no automatic write retry occurs. Cancellation after dispatch also records unknown. The remote side effect may still complete. Inspect data before asking again.

## Prompt files

Default editable UTF-8 files:
- config/prompts/personality.txt
- config/prompts/behavior.txt
- config/prompts/tools.txt

Direct ENV values take precedence:
- FOLLIANT_SYSTEM_PROMPT / FOLLIANT_SYSTEM_PROMPT_FILE
- FOLLIANT_BEHAVIOR_PROMPT / FOLLIANT_BEHAVIOR_PROMPT_FILE
- FOLLIANT_TOOL_PROMPT / FOLLIANT_TOOL_PROMPT_FILE

Relative paths resolve against the project root. Restart the application after changing these settings. Conversation.system_prompt supplements these instructions. Approval enforcement is implemented in Python and cannot be disabled by a chat prompt or tool result.

FOLLIANT_MAX_AGENT_STEPS defaults to 8 (1–32). At most 16 calls per model response. Tool arguments are bounded to 32 KB; stored results to approximately 64 KB and model-visible results to a smaller context-dependent limit. Truncated results carry an explicit marker. Context accounting includes serialized message/tool data and schemas. Old complete exchanges are dropped before active tool/result pairs; an oversized active exchange produces a clear error.

## Persistence

Migration b7c0312e5f44 adds conversation MCP selection, assistant protocol transcripts, run phase and ToolExecution. The parent run links executions to chat/messages. Completed assistant/tool sequences are restored as complete exchanges. Provider/model changes use the visible final text instead of replaying incompatible tool history.

On startup pending confirmations become interrupted, dispatched operations become unknown. No operation resumes automatically. Full checkpoints use the existing three-second cadence; approvals and tool transitions are persisted immediately.

## Provider scope

Runner depends only on ModelProvider. OpenAI currently uses the existing Responses API adapter; Ollama uses its own SDK chat format. This work does not add a Chat Completions adapter. A custom OpenAI-compatible endpoint must support the configured adapter's API. If a provider explicitly reports unsupported tools before any execution, the first request falls back to text-only.

## Checks

Mock tests: tests/test_agent.py. No real model or paid API is called. Chat Core migration tests also cover this schema. UI uses existing SSE snapshots for actual tool state; no simulated reasoning is displayed.

