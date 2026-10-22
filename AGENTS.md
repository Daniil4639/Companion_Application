\# AGENTS.md — Companion Application



\## Project overview



This repository contains a local-first personal companion application.



The application initially provides a calendar and a Kanban-style task manager. In later stages, it will support LLM providers, MCP integrations, Obsidian, an animated mascot, and a fantasy-world knowledge base.



\## Architecture



\- Backend: Python and FastAPI.

\- Database: SQLite, SQLAlchemy, Alembic.

\- Frontend: HTML, JS, CSS.

\- Use a modular monolith architecture.

\- Keep business logic separate from API routes, UI code, LLM integrations, and MCP adapters.

\- Calendar and task management must work independently of any AI provider.

\- Preserve existing API contracts unless changes are explicitly approved.



\## Development rules



\- Inspect the existing repository before proposing architectural changes.

\- Prefer incremental changes over large rewrites.

\- Do not introduce unnecessary dependencies or microservices.

\- Use the existing conventions where practical.

\- Do not alter existing database migrations without explaining the consequences.

\- Add or update tests for changes to business logic.

\- Run relevant tests and report failures.

\- Do not claim tests passed unless they were actually executed.

\- Avoid destructive database operations.

\- Do not read or expose secrets unless strictly necessary.

\- Explain significant architectural decisions.



\## Workflow



1\. Analyze the relevant code and dependencies.

2\. Identify risks and propose a small implementation plan.

3\. Make focused changes.

4\. Run available tests and checks.

5\. Summarize changes, test results, and remaining limitations.

