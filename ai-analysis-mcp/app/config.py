from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables
    (prefix AI_) or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_")

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_timeout_seconds: float = 60.0

    # Circuit breaker: if the rejection rate over the last N calls exceeds
    # this fraction, get_ai_engine_health() reports the breaker as tripped
    # and callers (e.g. the reporting engine) should stop auto-including
    # AI findings until it clears.
    circuit_breaker_window: int = 20
    circuit_breaker_rejection_threshold: float = 0.3

    audit_log_path: str = "audit_log.jsonl"


settings = Settings()
