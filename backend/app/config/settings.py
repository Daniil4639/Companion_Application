import os


class Settings:
    def __init__(self):
        self.port = os.getenv("APP_PORT", 8100)
        self.sql_lite_db_name = os.getenv("SQL_LITE_DB_NAME")


settings = Settings()