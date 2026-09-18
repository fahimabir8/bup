from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "GridWise Energy Optimizer"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # LLM
    llm_provider: Literal["openai", "ollama"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # Optimizer
    optimizer_timeout_seconds: int = 25

    # Request handling
    request_timeout_seconds: int = 30


settings = Settings()
