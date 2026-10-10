from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR.parent / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _database_url() -> str:
    default_path = (BASE_DIR / "data" / "enterprise_agent.db").as_posix()
    raw = os.getenv("DATABASE_URL")
    postgres_host = os.getenv("POSTGRES_HOST")
    if not raw and postgres_host:
        user = quote_plus(os.getenv("POSTGRES_USER", "enterprise"))
        password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
        database = quote_plus(os.getenv("POSTGRES_DB", "enterprise_agent"))
        port = int(os.getenv("POSTGRES_PORT", "5432"))
        raw = f"postgresql+psycopg://{user}:{password}@{postgres_host}:{port}/{database}"
    raw = raw or f"sqlite:///{default_path}"
    if raw.startswith("sqlite:///./"):
        relative_path = raw.removeprefix("sqlite:///./")
        return f"sqlite:///{(PROJECT_DIR / relative_path).resolve().as_posix()}"
    return raw


def _runtime_config_path() -> Path:
    raw = os.getenv("RUNTIME_CONFIG_PATH")
    if not raw:
        return BASE_DIR / "data" / "llm_config.json"
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "EnterpriseMind")
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = _database_url()
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me-32-bytes")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    auto_seed: bool = _as_bool(os.getenv("AUTO_SEED"), os.getenv("APP_ENV", "development") != "production")
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "10"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    db_pool_recycle_seconds: int = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_input_cost_per_million: float = float(
        os.getenv("LLM_INPUT_COST_PER_MILLION", "0")
    )
    llm_output_cost_per_million: float = float(
        os.getenv("LLM_OUTPUT_COST_PER_MILLION", "0")
    )
    runtime_config_path: Path = _runtime_config_path()
    rag_candidate_limit: int = int(os.getenv("RAG_CANDIDATE_LIMIT", "50"))

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    def validate(self) -> None:
        if self.access_token_minutes <= 0 or self.refresh_token_days <= 0:
            raise RuntimeError("令牌有效期必须大于 0")
        if self.max_upload_mb <= 0:
            raise RuntimeError("MAX_UPLOAD_MB 必须大于 0")
        if self.db_pool_size <= 0 or self.db_max_overflow < 0:
            raise RuntimeError("数据库连接池配置无效")
        if self.rag_candidate_limit < 1:
            raise RuntimeError("RAG 候选数量必须大于 0")
        if self.llm_input_cost_per_million < 0 or self.llm_output_cost_per_million < 0:
            raise RuntimeError("LLM Token 单价不能小于 0")
        if self.app_env == "production":
            insecure = {
                "dev-only-secret-change-me-32-bytes",
                "change-me-in-production-use-at-least-32-bytes",
                "replace-this-production-secret",
                "replace_with_a_random_secret_at_least_32_bytes",
            }
            if self.jwt_secret in insecure or len(self.jwt_secret.encode()) < 32:
                raise RuntimeError("生产环境必须配置至少 32 字节的非默认 JWT_SECRET")
            if self.auto_seed:
                raise RuntimeError("生产环境禁止启用 AUTO_SEED")


settings = Settings()
