"""
WaxPrep v2 — Settings
All environment variables loaded here. Import this anywhere you need config.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Supabase ──────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # ── Redis (Upstash) ───────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # ── Groq AI ───────────────────────────────
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_FAST_MODEL: str = "llama-3.1-8b-instant"
    GROQ_SMART_MODEL: str = "llama-3.3-70b-versatile"

    # ── Telegram ──────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # ── WhatsApp ──────────────────────────────
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    # ── Paystack ──────────────────────────────
    PAYSTACK_SECRET_KEY: str = os.getenv("PAYSTACK_SECRET_KEY", "")

    # ── App ───────────────────────────────────
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


# Create a single instance — import this everywhere
settings = Settings()
