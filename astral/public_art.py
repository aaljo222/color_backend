"""Explicit HTTPS deployment settings and anonymous, signed browser sessions."""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

COOKIE_NAME = '__Host-astral-session'


def deployment_config():
    if os.environ.get('ASTRAL_PUBLIC_IMAGE_ENABLED') != '1' or os.environ.get('VERCEL'):
        return None
    secret = os.environ.get('ASTRAL_SIGNING_SECRET', '')
    origin = os.environ.get('ASTRAL_PUBLIC_ORIGIN', '').rstrip('/')
    path = Path(os.environ.get('ASTRAL_ART_DB_PATH', ''))
    root = Path(__file__).resolve().parent.parent
    try:
        parsed = urlsplit(origin)
        daily = int(os.environ.get('ASTRAL_IMAGE_DAILY_LIMIT', '20'))
        total = int(os.environ.get('ASTRAL_IMAGE_TOTAL_LIMIT', '20'))
        valid = (len(secret) >= 32 and parsed.scheme == 'https' and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.path
                 and not parsed.query and not parsed.fragment
                 and path.is_absolute() and path.parent.is_dir()
                 and not path.resolve().is_relative_to(root)
                 and 1 <= daily <= 20 and 1 <= total <= 1000)
    except (ValueError, OSError):
        return None
    if not valid:
        return None
    return {'secret': secret.encode(), 'origin': origin, 'db_path': str(path),
            'daily_limit': daily, 'total_limit': total}


def issue_session(config):
    body = f'{secrets.token_hex(24)}.{int(time.time())+86400}'
    signature = hmac.new(config['secret'], ('session:'+body).encode(), hashlib.sha256).hexdigest()
    return body+'.'+signature


def session_owner(token, config):
    try:
        nonce, expiry, signature = token.split('.')
        body = nonce+'.'+expiry
        expected = hmac.new(config['secret'], ('session:'+body).encode(), hashlib.sha256).hexdigest()
        if len(nonce) != 48 or int(expiry) <= time.time() or not hmac.compare_digest(expected, signature):
            return None
        return hashlib.sha256(nonce.encode()).hexdigest()
    except (AttributeError, ValueError):
        return None
