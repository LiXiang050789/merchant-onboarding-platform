from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    jwt_secret: str = os.getenv("JWT_SECRET", "local-dev-secret-change-before-demo")
    mysql_dsn: str = os.getenv(
        "MYSQL_DSN",
        "mysql+asyncmy://merchant:merchant_pass@127.0.0.1:3306/merchant",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    mongo_url: str = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    mongo_db: str = os.getenv("MONGO_DB", "merchant_docs")
    access_token_minutes: int = 30
    refresh_token_days: int = 7


settings = Settings()
