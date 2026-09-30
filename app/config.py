import os


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eve_healthcare.db")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "local-development-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "local-development-webhook-secret")