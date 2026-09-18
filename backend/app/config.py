from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    jwt_secret: str = os.getenv("JWT_SECRET", "local-dev-secret-change-before-demo")
    mysql_dsn: str = os.getenv(
        "MYSQL_DSN",
        "mysql+asyncmy://merchant:merchant_pass@127.0.0.1:3306/merchant",
    )
    access_token_minutes: int = 30
    refresh_token_days: int = 7


settings = Settings()
