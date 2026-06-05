import re
from typing import Optional
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_PLATFORMS = {
    "tiktok": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
    "instagram": ["instagram.com", "www.instagram.com"],
    "facebook": ["facebook.com", "www.facebook.com", "fb.watch", "m.facebook.com"],
    "twitter": ["twitter.com", "www.twitter.com", "x.com", "www.x.com", "t.co"],
    "reddit": ["reddit.com", "www.reddit.com", "v.redd.it", "old.reddit.com"],
    "pinterest": ["pinterest.com", "www.pinterest.com", "pin.it", "pinterest.co.uk"],
    "vimeo": ["vimeo.com", "www.vimeo.com", "player.vimeo.com"],
    "dailymotion": ["dailymotion.com", "www.dailymotion.com", "dai.ly"],
    "threads": ["threads.net", "www.threads.net"],
    "youtube": ["youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"],
}

URL_PATTERN = re.compile(
    r"^https?://"
    r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
    r"localhost|"
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"(?::\d+)?"
    r"(?:/?|[/?]\S+)$",
    re.IGNORECASE,
)


def is_valid_url(url: str) -> bool:
    if not url or not url.strip():
        return False
    return bool(URL_PATTERN.match(url.strip()))


def detect_platform(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url.strip())
        hostname = parsed.netloc.lower().lstrip("www.")

        for platform, domains in SUPPORTED_PLATFORMS.items():
            normalized_domains = [d.lstrip("www.") for d in domains]
            if hostname in normalized_domains:
                return platform

        return None
    except Exception as e:
        logger.warning(f"Failed to detect platform for URL '{url}': {e}")
        return None


def validate_url(url: str) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Returns (is_valid, platform, error_message)
    """
    if not url or not url.strip():
        return False, None, "URL must not be empty"

    url = url.strip()

    if not is_valid_url(url):
        return False, None, "Invalid URL format"

    platform = detect_platform(url)
    if platform is None:
        return False, None, (
            "Unsupported platform. Supported platforms: "
            + ", ".join(p.capitalize() for p in SUPPORTED_PLATFORMS.keys())
        )

    return True, platform, None
