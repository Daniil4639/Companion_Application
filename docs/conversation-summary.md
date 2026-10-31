# Conversation summary and Chat MCP

Summarization runs after a successful answer, inside the same generation run and provider lease. The response remains visible while phase=summarizing is displayed. Sending stays disabled until the run finishes. Cancelling compression preserves the completed answer and the previously committed summary.

Configuration (ENV, restart required):
- FOLLIANT_SUMMARY_THRESHOLD=0.75: estimated fraction of available input budget.
- FOLLIANT_SUMMARY_KEEP_EXCHANGES=2: recent completed exchanges retained verbatim.

The estimate includes pending history, previous summary, system instructions and current MCP schema size. It uses the existing conservative token counter. Large context windows may never trigger summarization; Chat MCP still reads original messages. There is no message-count trigger.

SummaryService splits older material into bounded requests, even when one message is larger than the model window. It sends no tools and never forwards opaque provider continuations or reasoning payloads. It combines each new fragment with the tentative summary. Only after all requests succeed are content and boundary atomically replaced. Failure/cancellation leaves the old record unchanged. Model outputs are limited to 16 KB and the window-dependent cap; a maximum of 128 requests bounds one compression attempt.

ConversationSummary is covered by migration c8d1423f6055. The boundary references a completed assistant message. ContextBuilder uses summary as user-role DATA, not system instructions, and only history after the boundary. Full history is never deleted. During MCP execution the active call/result sequence remains intact; oversized results are bounded and old whole exchanges may be omitted. Summary is not generated in the middle of that sequence.

Provider concurrency:
- One active chat run per provider_id, checked transactionally by backend.
- Shared provider lease lock also serializes SDK clients for the same connection.
- The lease is deliberately held for the full run, including MCP approval waits and post-answer summarization.
- UI polls local availability every two seconds while a chat is visible. Backend remains authoritative.
- Distinct provider records pointing to the same endpoint are distinct concurrency slots.

Read-only tools on the existing local Folliant MCP server:
- chat_list(offset, limit): IDs, titles, title-derived topic, has_summary. No system prompts.
- chat_get_summary(conversation_id): exists flag, summary, boundary ID/position, timestamp.
- chat_read_messages(conversation_id, before, limit, text_offset): latest page in chronological order; next_before accesses older pages. At most 20 messages, 4000 characters each, with explicit truncation flags. For long messages, use limit=1, before=position+1 and the returned next_text_offset to read subsequent fragments.

All chat reads require ownership by the single local profile (user_id=1), use services and retain existing localhost MCP protection. Other-chat data enters the model only through explicit tool calls. These tools are visible to local clients and agents that select the Folliant MCP connection.

Tests use temporary SQLite and mock providers. Real models are never started by tests.

