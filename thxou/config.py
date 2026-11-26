import os


class Config:
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "local-only-change-me")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5000").rstrip("/")
    APP_ENV = os.getenv("APP_ENV", "development")
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    FAMILY_ACCESS_CODE = os.getenv("FAMILY_ACCESS_CODE", "")
    COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_SECURE = COOKIE_SECURE
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    DATA_TIMEOUT = (3.0, 10.0)
