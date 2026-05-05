"""
WaxPrep v2 — Helper Functions
Small utilities used across the codebase.
"""

import random
import string
import hashlib
import bcrypt
from datetime import datetime


def generate_wax_id() -> str:
    """Generate a unique WAX ID like WAX-A74892."""
    letter = random.choice(string.ascii_uppercase)
    digits = ''.join(random.choices(string.digits + string.ascii_uppercase, k=5))
    return f"WAX-{letter}{digits}"


def generate_recovery_code() -> str:
    """Generate a 12-character recovery code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))


def hash_pin(pin: str) -> str:
    """Hash a PIN with bcrypt. PIN must be a 4-digit string."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pin.encode('utf-8'), salt).decode('utf-8')


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Check if a PIN matches its hash."""
    try:
        return bcrypt.checkpw(pin.encode('utf-8'), pin_hash.encode('utf-8'))
    except Exception:
        return False


def clean_name(name: str) -> str:
    """Remove extra spaces and capitalize each word."""
    return ' '.join(word.capitalize() for word in name.strip().split())


def sanitize_input(text: str) -> str:
    """Remove dangerous characters, trim whitespace."""
    return text.strip()[:4000]


def nigeria_now() -> datetime:
    """Return current datetime. (Same as datetime.now() for now.)"""
    return datetime.now()


def nigeria_today() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return datetime.now().strftime("%Y-%m-%d")
