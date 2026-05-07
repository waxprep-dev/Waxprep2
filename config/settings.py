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
    # Multi-key rotation for rate limit bypass
    # Each key gets 100,000 tokens/day on free tier
    # With 3 keys = 300,000 tokens/day = ~30 active students
    @property
    def GROQ_API_KEYS(self) -> list:
        """Build list of API keys from environment variables."""
        keys = []
        # Primary key (original)
        key1 = os.getenv("GROQ_API_KEY", "")
        if key1:
            keys.append(key1)
        # Additional keys for rotation
        for i in range(2, 10):  # Support up to 9 keys
            key = os.getenv(f"GROQ_API_KEY_{i}", "")
            if key:
                keys.append(key)
        return keys if keys else [""]  # Fallback to empty string if no keys

    @property
    def GROQ_API_KEY(self) -> str:
        """Backward compatibility — returns the first available key."""
        keys = self.GROQ_API_KEYS
        return keys[0] if keys else ""

    GROQ_FAST_MODEL: str = "llama-3.1-8b-instant"
    GROQ_SMART_MODEL: str = "llama-3.3-70b-versatile"

    # ── Telegram ──────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

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
