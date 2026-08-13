from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via environment variables or a
    .env file (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_username: str | None = None
    elasticsearch_password: str | None = None

    signin_index_prefix: str = "m365-signin-logs"
    audit_index_prefix: str = "m365-audit-logs"

    # Impossible-travel heuristic: flag if the implied travel speed between
    # two successful sign-ins (from different countries) for the same user
    # exceeds this many km/h.
    impossible_travel_kmh_threshold: float = 900.0

    # M365 client app / auth values that indicate legacy (non-modern) auth.
    legacy_auth_clients: tuple[str, ...] = (
        "Authenticated SMTP",
        "POP",
        "IMAP4",
        "Exchange ActiveSync",
        "Other clients",
    )

    # Graph/Entra permission scopes treated as high-risk if consented to
    # mailbox data by a non-admin user.
    risky_consent_scopes: tuple[str, ...] = (
        "Mail.Read",
        "Mail.ReadWrite",
        "Mail.Send",
        "full_access_as_app",
        "Files.Read.All",
        "Sites.Read.All",
    )


settings = Settings()
