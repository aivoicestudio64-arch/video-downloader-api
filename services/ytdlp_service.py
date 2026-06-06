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


def _get_best_audio_url(raw_formats: List[Dict]) -> Optional[str]:
    """Returns the best available audio-only stream URL."""
    audio_formats = [
        f for f in raw_formats
        if f.get("url")
        and f.get("acodec") not in (None, "none")
        and f.get("vcodec") in (None, "none")
    ]
    if not audio_formats:
        return None
    # Prefer m4a, then any audio
    for preferred_ext in ("m4a", "aac", "mp4"):
        for fmt in audio_formats:
            if fmt.get("ext") == preferred_ext:
                return fmt["url"]
    return audio_formats[0]["url"]


def _parse_formats(raw_formats: List[Dict]) -> List[FormatInfo]:
    formats: List[FormatInfo] = []
    seen_qualities = set()

    # Find best audio URL once — attach to video-only streams
    best_audio_url = _get_best_audio_url(raw_formats)

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

        has_audio = fmt.get("acodec") not in (None, "none")

        formats.append(
            FormatInfo(
                quality=quality_label,
                ext=fmt.get("ext", "mp4"),
                url=fmt["url"],
                filesize=fmt.get("filesize") or fmt.get("filesize_approx"),
                vcodec=fmt.get("vcodec"),
                acodec=fmt.get("acodec"),
                # Attach separate audio URL only when the video stream has no audio
                audio_url=None if has_audio else best_audio_url,
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
    """
    Returns the best available direct video URL that already contains audio.
    If only separate video+audio streams exist, returns the video-only URL
    and logs a warning — callers should use /analyze audio_url for merging.
    """
    logger.info(f"[yt-dlp] Getting best download URL for platform={platform}")

    try:
        opts = _build_ydl_opts()
        # Prefer formats that already contain both video AND audio in one stream.
        # Falls back to best combined if no muxed format is available.
        opts["format"] = (
            "best[ext=mp4][vcodec!=none][acodec!=none]"
            "/best[vcodec!=none][acodec!=none]"
            "/bestvideo[ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo+bestaudio"
            "/best"
        )

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return None

        # When yt-dlp selects a muxed format, info["url"] is set directly.
        if info.get("url"):
            acodec = info.get("acodec", "none")
            vcodec = info.get("vcodec", "none")
            logger.info(
                f"[yt-dlp] Single-stream URL found — vcodec={vcodec}, acodec={acodec}"
            )
            return info["url"]

        # When yt-dlp selects separate video+audio, they appear in requested_formats.
        requested_formats = info.get("requested_formats")
        if requested_formats:
            video_url: Optional[str] = None
            audio_url: Optional[str] = None

            for fmt in requested_formats:
                vcodec = fmt.get("vcodec", "none")
                acodec = fmt.get("acodec", "none")
                if vcodec != "none" and acodec != "none":
                    # Lucky — this single stream has both
                    logger.info("[yt-dlp] Found muxed stream inside requested_formats")
                    return fmt["url"]
                if vcodec != "none" and not video_url:
                    video_url = fmt["url"]
                if acodec != "none" and vcodec == "none" and not audio_url:
                    audio_url = fmt["url"]

            if video_url and audio_url:
                # Both streams found — return video URL and log audio separately.
                # The client must use /analyze to get audio_url for local merging,
                # or use the /download/merged endpoint (if implemented).
                logger.warning(
                    "[yt-dlp] Separate video+audio streams detected. "
                    f"video={video_url[:60]}... audio={audio_url[:60]}... "
                    "Returning video URL only — audio_url available via /analyze."
                )
                # Return the video URL; audio_url is exposed via /analyze formats
                return video_url

            if video_url:
                return video_url

        # Last resort: pick the highest-resolution URL from formats list
        raw_formats = info.get("formats", [])
        muxed = [
            f for f in raw_formats
            if f.get("url")
            and f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
        ]
        if muxed:
            best = sorted(muxed, key=lambda f: f.get("height") or 0, reverse=True)
            logger.info("[yt-dlp] Returning best muxed fallback format")
            return best[0]["url"]

        for fmt in sorted(raw_formats, key=lambda f: f.get("height") or 0, reverse=True):
            if fmt.get("url"):
                return fmt["url"]

        return None

    except Exception as e:
        logger.error(f"[yt-dlp] Failed to get best download URL: {e}", exc_info=True)
        return None
