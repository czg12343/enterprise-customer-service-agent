from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from threading import RLock

from app.core.config import settings
from app.core.secret_codec import decrypt_secret, encrypt_secret

_lock = RLock()


@dataclass(frozen=True)
class LLMRuntimeConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    enabled: bool
    source: str

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key and self.model)


def _environment_config() -> LLMRuntimeConfig:
    configured = bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model)
    return LLMRuntimeConfig(
        base_url=settings.llm_base_url.rstrip("/"),
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        enabled=configured,
        source="environment",
    )


def get_runtime_llm_config() -> LLMRuntimeConfig:
    with _lock:
        path = settings.runtime_config_path
        if not path.is_file():
            return _environment_config()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return LLMRuntimeConfig(
                base_url=str(data.get("base_url", "")).rstrip("/"),
                api_key=decrypt_secret(str(data.get("api_key_encrypted", ""))),
                model=str(data.get("model", "")),
                enabled=bool(data.get("enabled", False)),
                source="admin",
            )
        except (OSError, ValueError, TypeError):
            return _environment_config()


def save_runtime_llm_config(
    *,
    base_url: str,
    model: str,
    enabled: bool,
    api_key: str | None = None,
    clear_api_key: bool = False,
) -> LLMRuntimeConfig:
    with _lock:
        current = get_runtime_llm_config()
        next_api_key = "" if clear_api_key else (api_key or current.api_key)
        config = LLMRuntimeConfig(
            base_url=base_url.rstrip("/"),
            api_key=next_api_key,
            model=model,
            enabled=enabled,
            source="admin",
        )
        if enabled and not config.ready:
            raise ValueError("启用大模型前必须填写 Base URL、API Key 和模型名称")

        path = settings.runtime_config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "base_url": config.base_url,
                    "api_key_encrypted": encrypt_secret(config.api_key),
                    "model": config.model,
                    "enabled": config.enabled,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
        return config
