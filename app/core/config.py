from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    data_dir: str = "/data"
    tolerance_total: float = 0.02
    tz: str = "Europe/Paris"

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def pdfs_path(self) -> Path:
        return self.data_path / "pdfs"

    @property
    def deleted_pdfs_path(self) -> Path:
        return self.pdfs_path / "deleted"

    @property
    def exports_path(self) -> Path:
        return self.data_path / "exports"

    @property
    def db_path(self) -> Path:
        return self.data_path / "app.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
