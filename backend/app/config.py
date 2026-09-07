from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    stripe_secret_key: str = ""
    slack_bot_token: str = ""
    slack_fraud_ops_channel: str = "#fraud-ops"
    github_pat: str = ""
    github_demo_repo: str = ""

    database_url: str | None = None
    # Set on Cloud Run via --add-cloudsql-instances; absence of DATABASE_URL
    # means "use the /cloudsql socket instead".
    cloud_sql_connection_name: str | None = None
    db_user: str = "casework"
    db_password: str = "casework"
    db_name: str = "casework"

    frontend_origin: str = "http://localhost:5173"

    @property
    def db_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        if self.cloud_sql_connection_name:
            socket_dir = f"/cloudsql/{self.cloud_sql_connection_name}"
            return (
                f"postgresql://{self.db_user}:{self.db_password}@/{self.db_name}"
                f"?host={socket_dir}"
            )
        raise RuntimeError(
            "Neither DATABASE_URL nor CLOUD_SQL_CONNECTION_NAME is set."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
