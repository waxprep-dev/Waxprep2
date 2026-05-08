"""
WaxPrep Automated Test Harness — Configuration
All settings, URLs, keys, and thresholds in one place.
"""

import os

# ═══════════════════════════════════════════════
# CONNECTIONS
# ═══════════════════════════════════════════════

RENDER_URL = os.getenv("WAXPREP_RENDER_URL", "https://waxprep2.onrender.com")
WEBHOOK_PATH = "/webhook/telegram"
HEALTH_PATH = "/health"

# GitHub for auto-creating issues on failures
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "waxprep-dev/waxprep-v2"

# ═══════════════════════════════════════════════
# TEST MODES
# ═══════════════════════════════════════════════

# Tier presets
TIERS = {
    "quick": {"scenarios": 50, "duration_minutes": 5, "mock_groq": False},
    "medium": {"scenarios": 200, "duration_minutes": 30, "mock_groq": False},
    "deep": {"scenarios": 500, "duration_minutes": 120, "mock_groq": True},
    "chaos": {"scenarios": 2000, "duration_minutes": 480, "mock_groq": True},
}

# Default when no tier specified
DEFAULT_SCENARIOS = 500
DEFAULT_DURATION_MINUTES = 240  # 4 hours
MAX_DURATION_MINUTES = 480  # 8 hours max

# ═══════════════════════════════════════════════
# CONCURRENCY & TIMING
# ═══════════════════════════════════════════════

CONCURRENT_SCENARIOS = 5  # Run 5 scenarios at once
MESSAGE_DELAY_MIN = 0.5   # Seconds between messages in a scenario
MESSAGE_DELAY_MAX = 3.0   # Random delay to feel natural
REQUEST_TIMEOUT = 60       # Seconds (Render cold start = 50s)
RETRY_MAX = 3
RETRY_BACKOFF = [1, 2, 4, 8]  # Seconds between retries

# ═══════════════════════════════════════════════
# CHECKPOINTS & RESILIENCE
# ═══════════════════════════════════════════════

CHECKPOINT_INTERVAL = 10  # Save progress every 10 scenarios
CASCADING_FAILURE_THRESHOLD = 10  # 10 consecutive failures = pause
BATTERY_LOW_THRESHOLD = 15  # Stop at 15% battery
WARMUP_RETRIES = 3  # Ping /health before starting

# ═══════════════════════════════════════════════
# GROQ TOKEN MANAGEMENT
# ═══════════════════════════════════════════════

GROQ_DAILY_LIMIT = 100000  # Tokens per key per day
GROQ_STOP_AT_PERCENT = 80  # Stop tests at 80% of limit
GROQ_USAGE_CHECK_INTERVAL = 60  # Seconds between token checks

# ═══════════════════════════════════════════════
# TEST DATA ISOLATION
# ═══════════════════════════════════════════════

TEST_PREFIX = "test_"  # All test student IDs start with this
TEST_REDIS_TTL = 3600   # 1 hour (test keys auto-expire)
TEST_WAX_ID_PREFIX = "TEST-"

# ═══════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════

REPORT_DIR = "test_reports"
CREATE_GITHUB_ISSUES = True  # Auto-create issues for failures
REPORT_FORMAT = "markdown"  # Also "json" available

# ═══════════════════════════════════════════════
# FAILURE SEVERITY WEIGHTS
# ═══════════════════════════════════════════════

FAILURE_WEIGHTS = {
    "CRITICAL": 10,   # Trust-breaking: boundaries ignored, safety failures
    "HIGH": 8,        # Emotional: vulnerability redirected, gratitude dismissed
    "MEDIUM": 5,      # Quality: wrong answer, Student Model not loaded
    "LOW": 2,         # Preference: wrong domain used but not rejected
    "COSMETIC": 1,    # Tone slightly off but functionally correct
}

# ═══════════════════════════════════════════════
# FEATURE DETECTION (Auto-test new code)
# ═══════════════════════════════════════════════

WATCHED_MODULES = [
    "brain/detectors.py",
    "brain/state.py",
    "brain/student_model.py",
    "telegram/handler.py",
    "telegram/onboarding.py",
    "ai/prompts.py",
    "ai/brain.py",
    "content/jamb_combinations.py",
    "content/jamb_checker.py",
]

# Patterns the harness auto-detects for testing
AUTO_DETECT_PATTERNS = {
    "detector": {
        "file": "brain/detectors.py",
        "trigger": "async def detect_",
        "generate": "detection_scenarios",
    },
    "state": {
        "file": "brain/state.py",
        "trigger": "class StudentState",
        "generate": "state_transition_scenarios",
    },
    "subject": {
        "file": "telegram/handler.py",
        "trigger": "SUBJECT_MAP",
        "generate": "subject_coverage_scenarios",
    },
    "jamb_course": {
        "file": "content/jamb_combinations.py",
        "trigger": "JAMB_COMBINATIONS",
        "generate": "jamb_check_scenarios",
    },
}
