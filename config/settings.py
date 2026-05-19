"""
WaxPrep v2 — Settings
All environment variables loaded here. Import this anywhere you need config.

Single source of truth for all configuration. Use `from config.settings import settings`
and access values via `settings.KEY_NAME`.

Security: __repr__ masks sensitive values so accidental logging doesn't leak credentials.
"""

import os
import logging
import warnings

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — env vars come from the platform

logger = logging.getLogger("waxprep.settings")


class Settings:
    """
    Centralized application settings loaded from environment variables.
    
    All values have sensible defaults for development.
    Production deployments should set all required variables.
    """
    
    # ── Supabase ──────────────────────────────
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    # TODO Phase 3: Add SUPABASE_ANON_KEY for read operations.
    # Currently all operations use the service key (bypasses RLS).
    # Student data isolation relies entirely on application-level WHERE clauses.
    # Also: add pre-commit hook to prevent logging of SUPABASE_SERVICE_KEY.
    # NOTE: SUPABASE_SERVICE_KEY is the service role key — it bypasses RLS.
    # NEVER log this value. NEVER expose it in error messages.
    # Use settings.SUPABASE_ANON_KEY for public operations when available.

    # ── Redis (Upstash) ───────────────────────
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # ── Groq AI ───────────────────────────────
    # Multi-key rotation for rate limit bypass.
    # Each key gets 100,000 tokens/day on Groq free tier.
    # Add extra keys as GROQ_API_KEY_2, GROQ_API_KEY_3, etc.
    _groq_keys_cache: list = None

    @property
    def GROQ_API_KEYS(self) -> list:
        """
        Build list of API keys from environment variables.
        
        Cached after first access — computed once, used thousands of times.
        Deduplicated to prevent accidental double-use of the same key.
        Returns empty list if no keys configured (callers must handle gracefully).
        """
        if self._groq_keys_cache is not None:
            return self._groq_keys_cache
        
        keys = []
        # Primary key
        key1 = os.getenv("GROQ_API_KEY", "")
        if key1:
            keys.append(key1)
        # Additional rotation keys (up to 9 total — GROQ_API_KEY_2 through GROQ_API_KEY_9)
        for i in range(2, 10):
            key = os.getenv(f"GROQ_API_KEY_{i}", "")
            if key:
                keys.append(key)
        
        # Deduplicate while preserving order
        seen = set()
        unique_keys = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                unique_keys.append(k)
        
        # If no keys configured, log critical warning (don't silently return [""])
        if not unique_keys:
            logger.critical(
                "No Groq API keys configured! AI functionality will fail. "
                "Set GROQ_API_KEY in your environment variables."
            )
            self._groq_keys_cache = []
            return []
        
        logger.info(f"Loaded {len(unique_keys)} Groq API key(s)")
        self._groq_keys_cache = unique_keys
        return unique_keys

    @property
    def GROQ_API_KEY(self) -> str:
        """
        Backward compatibility — returns the first available key.
        
        Use GROQ_API_KEYS for multi-key rotation.
        This property exists for code that expects a single key.
        """
        warnings.warn(
            "GROQ_API_KEY is deprecated. Use GROQ_API_KEYS instead.",
            DeprecationWarning,
            stacklevel=2
        )
        keys = self.GROQ_API_KEYS
        return keys[0] if keys else ""

    # Model names — wrapped in env vars so they can be hot-swapped
    # without code deployment when Groq deprecates older models.
    GROQ_FAST_MODEL: str = os.getenv(
        "GROQ_FAST_MODEL",
        "llama-3.1-8b-instant"
    )
    GROQ_SMART_MODEL: str = os.getenv(
        "GROQ_SMART_MODEL",
        "llama-3.3-70b-versatile"
    )

    # ── Telegram ──────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    # WARNING: TELEGRAM_WEBHOOK_SECRET should be set in production.
    # Without it, the webhook accepts requests from anyone.

    # ── WhatsApp ──────────────────────────────
    WHATSAPP_TOKEN: str = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    # ── Paystack ──────────────────────────────
    PAYSTACK_SECRET_KEY: str = os.getenv("PAYSTACK_SECRET_KEY", "")

    # ── App ───────────────────────────────────
    # Use ENVIRONMENT everywhere (not ENV — standardized across codebase)
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENVIRONMENT == "development"
    
    def __repr__(self) -> str:
        """
        Safe representation — masks sensitive values.
        
        If settings is accidentally logged or included in an error message,
        only non-sensitive info is shown. Actual keys are never exposed.
        """
        return (
            f"Settings("
            f"ENVIRONMENT={self.ENVIRONMENT}, "
            f"SUPABASE_URL={'configured' if self.SUPABASE_URL else 'not set'}, "
            f"SUPABASE_SERVICE_KEY={'configured' if self.SUPABASE_SERVICE_KEY else 'not set'}, "
            f"REDIS_URL={'configured' if self.REDIS_URL else 'not set'}, "
            f"GROQ_KEYS={len(self.GROQ_API_KEYS)} key(s) configured, "
            f"TELEGRAM_BOT_TOKEN={'configured' if self.TELEGRAM_BOT_TOKEN else 'not set'}, "
            f"TELEGRAM_WEBHOOK_SECRET={'configured' if self.TELEGRAM_WEBHOOK_SECRET else 'not set'}, "
            f"WHATSAPP={'configured' if self.WHATSAPP_TOKEN else 'not set'}, "
            f"PAYSTACK={'configured' if self.PAYSTACK_SECRET_KEY else 'not set'}"
            f")"
        )
    
    def validate(self) -> list:
        """
        Validate that all required settings are configured.
        
        Returns a list of warning messages. Empty list means all good.
        Call this from the lifespan startup in main.py.
        """
        warnings = []
        
        # Always check — bot can't function without these in any environment
        if not self.TELEGRAM_BOT_TOKEN:
            warnings.append("TELEGRAM_BOT_TOKEN is not set — bot will not start")
        if not self.GROQ_API_KEYS or not self.GROQ_API_KEYS[0]:
            warnings.append("No Groq API keys configured — AI will fail")
        if not self.REDIS_URL:
            warnings.append("REDIS_URL is not set — conversation history will fail")
        if not self.SUPABASE_URL:
            warnings.append("SUPABASE_URL is not set — student data will fail")
        
        # Production-only checks
        if self.is_production:
            if not self.SUPABASE_SERVICE_KEY:
                warnings.append("SUPABASE_SERVICE_KEY is not set")
            if not self.TELEGRAM_WEBHOOK_SECRET:
                warnings.append(
                    "TELEGRAM_WEBHOOK_SECRET is not set — webhook is UNPROTECTED"
                )
        
        for warning in warnings:
            logger.warning(f"⚠️ CONFIG: {warning}")
        
        return warnings


# Create a single instance — import this everywhere
settings = Settings()
