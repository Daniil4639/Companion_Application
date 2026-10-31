import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings:
    def __init__(self):
        if os.getenv("COMPANION_LOAD_DOTENV", "1") != "0":
            load_dotenv(PROJECT_ROOT / ".env", override=False)

        self.port = int(os.getenv("APP_PORT", "8181"))
        self.system_prompt = os.getenv("FOLLIANT_SYSTEM_PROMPT",
                                       "Ты — Folliant, внимательный и мудрый помощник-наставник. Отвечай ясно, доброжелательно и честно.")
        if not 1 <= self.port <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")

        def prompt(name, filename, fallback=None):
            direct = os.getenv(name)
            if direct is not None:
                return direct
            path = Path(os.getenv(name + "_FILE", "config/prompts/" + filename + ".txt"))
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if os.getenv(name + "_FILE") or path.exists():
                return path.read_text(encoding="utf-8").strip()
            return fallback or ""

        self.system_prompt = prompt("FOLLIANT_SYSTEM_PROMPT", "personality", self.system_prompt)
        self.behavior_prompt = prompt("FOLLIANT_BEHAVIOR_PROMPT", "behavior")
        self.tool_prompt = prompt("FOLLIANT_TOOL_PROMPT", "tools")
        self.max_agent_steps = int(os.getenv("FOLLIANT_MAX_AGENT_STEPS", "8"))
        self.summary_threshold = float(os.getenv("FOLLIANT_SUMMARY_THRESHOLD", "0.75"))
        self.summary_keep_exchanges = int(os.getenv("FOLLIANT_SUMMARY_KEEP_EXCHANGES", "2"))
        if not 0.1 <= self.summary_threshold <= 1 or not 1 <= self.summary_keep_exchanges <= 20:
            raise ValueError("Invalid summary threshold or keep-exchanges setting")
        if not 1 <= self.max_agent_steps <= 32:
            raise ValueError("FOLLIANT_MAX_AGENT_STEPS must be 1..32")
        self.trusted_read_servers = set(filter(None, os.getenv("FOLLIANT_TRUSTED_READ_SERVERS", "folliant").split(",")))

        self.sql_lite_db_name = os.getenv("SQL_LITE_DB_NAME", "companion-app")

        default_path = PROJECT_ROOT / (self.sql_lite_db_name + ".db")
        url = make_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///" + default_path.as_posix()))

        if url.drivername != "sqlite+aiosqlite" or not url.database:
            raise ValueError("DATABASE_URL must use sqlite+aiosqlite")

        if url.database != ":memory:":
            path = Path(url.database)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            url = url.set(database=path.resolve().as_posix())

        self.database_url = url.render_as_string(hide_password=False)


settings = Settings()