import os
from typing import Any, Dict, List, Optional

import yt_dlp

from models.responses import FormatInfo
from utils.logger import get_logger

logger = get_logger(__name__)

PLATFORM_DISPLAY_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "twitter": "X (Twitter)",
    "reddit": "Reddit",
    "pinterest": "Pinterest",
    "vimeo": "Vimeo",
    "dailymotion": "Dailymotion",
    "threads": "Threads",
    "youtube": "YouTube",
}


def _build_ydl_opts(extract_flat: bool = False) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": extract_flat,
        "socket_timeout": 30,
        "retries": 3,
    }

    http_proxy = os.getenv("HTTP_PROXY", "")
    if http_proxy:
        opts["proxy"] = http_proxy

    user_agent = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
    )
    opts["http_headers"] = {"User-Agent": user_agent}

    return opts


def _parse_formats(raw_formats: List[Dict]) -> List[FormatInfo]:
    formats: List[FormatInfo] = []
    seen_qualities = set()

    video_formats = [
        f
        for f in raw_formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("height")
    ]

    video_formats.sort(key=lambda f: f.get("height", 0), reverse=True)

    for fmt in video_formats:
        height = fmt.get("height")
        quality_label = f"{height}p" if height else "unknown"

        if quality_label in seen_qualities:
            continue
        seen_qualities.add(quality_label)

        formats.append(
            FormatInfo(
                quality=quality_label,
                ext=fmt.get("ext", "mp4"),
                url=fmt["url"],
                filesize=fmt.get("filesize") or fmt.get("filesize_approx"),
                vcodec=fmt.get("vcodec"),
                acodec=fmt.get("acodec"),
            )
        )

    if not formats:
        audio_formats = [
            f
            for f in raw_formats
            if f.get("url")
            and f.get("acodec") not in (None, "none")
            and f.get("vcodec") in (None, "none")
        ]
        for fmt in audio_formats[:3]:
            abr = fmt.get("abr")
            quality_label = f"{int(abr)}kbps" if abr else "audio"
            formats.append(
                FormatInfo(
                    quality=quality_label,
                    ext=fmt.get("ext", "mp3"),
                    url=fmt["url"],
                    filesize=fmt.get("filesize"),
                    vcodec=None,
                    acodec=fmt.get("acodec"),
                )
            )

    if not formats:
        for fmt in raw_formats:
            if fmt.get("url"):
                formats.append(
                    FormatInfo(
                        quality="best",
                        ext=fmt.get("ext", "mp4"),
                        url=fmt["url"],
                        filesize=fmt.get("filesize"),
                    )
                )
                break

    return formats


def extract_info(url: str, platform: str) -> Dict[str, Any]:
    logger.info(f"[yt-dlp] Extracting info for platform={platform} url={url}")

    try:
        with yt_dlp.YoutubeDL(_build_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError("yt-dlp returned no information for this URL")

        raw_formats: List[Dict] = info.get("formats", [])
        parsed_formats = _parse_formats(raw_formats)

        duration_raw = info.get("duration")
        duration = int(duration_raw) if duration_raw is not None else None

        display_platform = PLATFORM_DISPLAY_NAMES.get(platform, platform.capitalize())

        extractor = info.get("extractor_key", "").lower()
        if not display_platform or display_platform == platform.capitalize():
            for key, display in PLATFORM_DISPLAY_NAMES.items():
                if key in extractor:
                    display_platform = display
                    break

        result = {
            "title": info.get("title") or info.get("description", "Untitled"),
            "thumbnail": info.get("thumbnail"),
            "duration": duration,
            "platform": display_platform,
            "formats": parsed_formats,
            "raw_url": url,
        }

        logger.info(
            f"[yt-dlp] Successfully extracted: title='{result['title']}', "
            f"formats={len(parsed_formats)}, platform={display_platform}"
        )
        return result

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"[yt-dlp] DownloadError for {url}: {e}")
        raise RuntimeError(f"Failed to extract video info: {str(e)}")
    except yt_dlp.utils.ExtractorError as e:
        logger.error(f"[yt-dlp] ExtractorError for {url}: {e}")
        raise RuntimeError(f"Extractor error: {str(e)}")
    except Exception as e:
        logger.error(f"[yt-dlp] Unexpected error for {url}: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error during extraction: {str(e)}")


def get_best_download_url(url: str, platform: str) -> Optional[str]:
    logger.info(f"[yt-dlp] Getting best download URL for platform={platform}")

    try:
        opts = _build_ydl_opts()
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        requested_formats = info.get("requested_formats")
        if requested_formats:
            for fmt in requested_formats:
                if fmt.get("url"):
                    logger.info("[yt-dlp] Returning best requested format URL")
                    return fmt["url"]

        if info.get("url"):
            return info["url"]

        raw_formats = info.get("formats", [])
        for fmt in sorted(
            raw_formats,
            key=lambda f: (f.get("height") or 0),
            reverse=True,
        ):
            if fmt.get("url"):
                return fmt["url"]

        return None

    except Exception as e:
        logger.error(f"[yt-dlp] Failed to get best download URL: {e}", exc_info=True)
        return None
