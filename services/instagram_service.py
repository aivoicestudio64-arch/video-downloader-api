import re
from typing import Any, Dict, Optional

import instaloader

from services import ytdlp_service
from utils.logger import get_logger

logger = get_logger(__name__)

_loader = instaloader.Instaloader(
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    quiet=True,
)


def _extract_shortcode(url: str) -> Optional[str]:
    patterns = [
        r"instagram\.com/p/([A-Za-z0-9_-]+)",
        r"instagram\.com/reel/([A-Za-z0-9_-]+)",
        r"instagram\.com/tv/([A-Za-z0-9_-]+)",
        r"instagram\.com/stories/[^/]+/(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _extract_via_instaloader(url: str) -> Optional[Dict[str, Any]]:
    """
    Tries to extract post data via Instaloader.
    Returns None on any failure so caller can fall back to yt-dlp.
    NOTE: Instagram's video_url from Instaloader already contains audio —
    it is a fully muxed CDN URL. No separate audio stream needed.
    """
    shortcode = _extract_shortcode(url)
    if not shortcode:
        logger.warning(f"[Instagram] Could not extract shortcode from: {url}")
        return None

    logger.info(f"[Instagram] Instaloader → shortcode={shortcode}")

    try:
        post = instaloader.Post.from_shortcode(_loader.context, shortcode)

        video_url: Optional[str] = None
        thumbnail: Optional[str] = None

        if post.is_video:
            video_url = post.video_url   # ← muxed MP4 (video + audio)
            thumbnail = post.url
        else:
            thumbnail = post.url

        caption = post.caption or ""
        title = caption[:120].strip() if caption else f"Instagram Post {shortcode}"
        title = re.sub(r"\s+", " ", title)

        duration: Optional[int] = None
        if post.is_video and post.video_duration:
            duration = int(post.video_duration)

        formats = []
        if video_url:
            formats.append(
                {
                    "quality": "best",
                    "ext": "mp4",
                    "url": video_url,
                    "filesize": None,
                    # Both codecs present — this is a muxed stream
                    "vcodec": "h264",
                    "acodec": "aac",
                    "audio_url": None,   # no separate audio needed
                }
            )

        logger.info(
            f"[Instagram] Instaloader OK — is_video={post.is_video}, "
            f"shortcode={shortcode}"
        )
        return {
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "platform": "Instagram",
            "formats": formats,
            "raw_url": url,
        }

    except instaloader.exceptions.InstaloaderException as e:
        logger.warning(f"[Instagram] Instaloader error ({shortcode}): {e}")
        return None
    except Exception as e:
        logger.warning(
            f"[Instagram] Unexpected Instaloader error ({shortcode}): {e}",
            exc_info=True,
        )
        return None


def extract_info(url: str) -> Dict[str, Any]:
    result = _extract_via_instaloader(url)
    if result is not None:
        return result
    logger.info(f"[Instagram] Falling back to yt-dlp for: {url}")
    return ytdlp_service.extract_info(url, "instagram")


def get_best_download_url(url: str) -> Optional[str]:
    """
    Returns a muxed (video+audio) URL.
    Instaloader's video_url is always muxed — preferred over yt-dlp
    which may return a video-only stream.
    """
    shortcode = _extract_shortcode(url)

    if shortcode:
        try:
            post = instaloader.Post.from_shortcode(_loader.context, shortcode)
            if post.is_video and post.video_url:
                logger.info(
                    f"[Instagram] Muxed video URL from Instaloader — "
                    f"shortcode={shortcode}"
                )
                return post.video_url   # ← always has audio
        except Exception as e:
            logger.warning(f"[Instagram] Instaloader URL extraction failed: {e}")

    logger.info("[Instagram] Falling back to yt-dlp for download URL")
    return ytdlp_service.get_best_download_url(url, "instagram")
