import os
import shutil
import subprocess
import tempfile
from typing import Optional

import httpx
import yt_dlp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from models.requests import DownloadRequest
from models.responses import DownloadResponse
from services import instagram_service, ytdlp_service
from utils.logger import get_logger
from utils.validators import validate_url

logger = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(tags=["Download"])

DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "120"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "500"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _sanitize_title(raw: str) -> str:
    safe = "".join(c for c in raw if c.isalnum() or c in " _-")
    return safe.strip()[:80] or "video"


def _extract_streams(url: str, platform: str) -> dict:
    """
    Calls yt-dlp and returns:
      { video_url, audio_url (or None), title, ext }
    Prefers formats that already contain both streams (muxed).
    """
    opts = ytdlp_service._build_ydl_opts()
    opts["format"] = (
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
        "/bestvideo[ext=mp4]+bestaudio"
        "/bestvideo+bestaudio"
        "/best[ext=mp4]"
        "/best"
    )

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError("yt-dlp returned no information for this URL")

    title = _sanitize_title(
        info.get("title") or info.get("description") or "video"
    )

    requested = info.get("requested_formats")

    # ── Separate video + audio streams ──
    if requested and len(requested) >= 2:
        video_url: Optional[str] = None
        audio_url: Optional[str] = None
        for fmt in requested:
            vc = fmt.get("vcodec", "none")
            ac = fmt.get("acodec", "none")
            if vc not in (None, "none") and not video_url:
                video_url = fmt["url"]
            if ac not in (None, "none") and vc in (None, "none") and not audio_url:
                audio_url = fmt["url"]
        if video_url and audio_url:
            logger.info(f"[streams] Separate v+a streams for platform={platform}")
            return {"video_url": video_url, "audio_url": audio_url,
                    "title": title, "ext": "mp4"}

    # ── Single muxed stream ──
    if info.get("url"):
        logger.info("[streams] Single muxed stream found")
        return {"video_url": info["url"], "audio_url": None,
                "title": title, "ext": info.get("ext", "mp4")}

    # ── Fallback: scan formats list ──
    raw = info.get("formats", [])
    muxed = [
        f for f in raw
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if muxed:
        best = sorted(muxed, key=lambda f: f.get("height") or 0, reverse=True)[0]
        logger.info("[streams] Using best muxed fallback format")
        return {"video_url": best["url"], "audio_url": None,
                "title": title, "ext": best.get("ext", "mp4")}

    raise RuntimeError("No downloadable stream found")


def _download_file(stream_url: str, dest: str, label: str) -> None:
    """Downloads a remote URL to a local file path."""
    logger.info(f"[dl] Downloading {label}…")
    total = 0
    with httpx.stream(
        "GET", stream_url,
        headers=_HTTP_HEADERS,
        timeout=DOWNLOAD_TIMEOUT,
        follow_redirects=True,
    ) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(256 * 1024):
                total += len(chunk)
                if total > MAX_FILE_BYTES:
                    raise RuntimeError(
                        f"File exceeds the {MAX_FILE_MB}MB size limit"
                    )
                f.write(chunk)
    logger.info(f"[dl] {label} done — {total / 1024 / 1024:.1f} MB")


def _ffmpeg_merge(video: str, audio: str, out: str) -> None:
    """Merges video + audio with ffmpeg (stream copy, no re-encode)."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-i", audio,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        out,
    ]
    logger.info(f"[ffmpeg] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, timeout=DOWNLOAD_TIMEOUT)
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace")[-400:]
        logger.error(f"[ffmpeg] Failed:\n{err}")
        raise RuntimeError(f"ffmpeg merge failed: {err}")
    logger.info("[ffmpeg] Merge complete ✓")


def _stream_file(path: str, tmpdir: str):
    """Generator — yields file chunks then removes tmpdir."""
    try:
        with open(path, "rb") as f:
            while chunk := f.read(512 * 1024):
                yield chunk
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info(f"[cleanup] Removed {tmpdir}")


# ─────────────────────────────────────────────
# /download  — returns a direct URL (legacy, kept for compatibility)
# ─────────────────────────────────────────────

@router.post("/download", response_model=DownloadResponse)
@limiter.limit("10/minute")
async def download(request: Request, body: DownloadRequest):
    url = body.url
    logger.info(f"[POST /download] {url}")

    is_valid, platform, error_msg = validate_url(url)
    if not is_valid:
        raise HTTPException(status_code=422, detail=error_msg)

    try:
        if platform == "instagram":
            download_url = instagram_service.get_best_download_url(url)
            display_platform = "Instagram"
        else:
            download_url = ytdlp_service.get_best_download_url(url, platform)
            from services.ytdlp_service import PLATFORM_DISPLAY_NAMES
            display_platform = PLATFORM_DISPLAY_NAMES.get(platform, platform.capitalize())

        if not download_url:
            raise HTTPException(
                status_code=422,
                detail="Could not extract a downloadable URL",
            )

        return DownloadResponse(
            success=True,
            download_url=download_url,
            platform=display_platform,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[POST /download] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Download failed")


# ─────────────────────────────────────────────
# /download/merged  — server merges video+audio, sends full MP4
# ─────────────────────────────────────────────

@router.post("/download/merged")
@limiter.limit("5/minute")
async def download_merged(request: Request, body: DownloadRequest):
    """
    Downloads video and audio streams on the server, merges them with
    ffmpeg, and streams the final MP4 to the client — always with sound.
    """
    url = body.url
    logger.info(f"[POST /download/merged] {url}")

    is_valid, platform, error_msg = validate_url(url)
    if not is_valid:
        raise HTTPException(status_code=422, detail=error_msg)

    try:
        # ── 1. Extract stream info ──
        if platform == "instagram":
            insta = instagram_service._extract_via_instaloader(url)
            if insta and insta.get("formats"):
                fmt = insta["formats"][0]
                video_url = fmt["url"] if isinstance(fmt, dict) else fmt.url
                streams = {
                    "video_url": video_url,
                    "audio_url": None,
                    "title": insta.get("title", "instagram_video"),
                    "ext": "mp4",
                }
            else:
                streams = _extract_streams(url, platform)
        else:
            streams = _extract_streams(url, platform)

        video_url: str = streams["video_url"]
        audio_url: Optional[str] = streams["audio_url"]
        title: str = streams["title"]

        # ── 2. Already muxed → proxy directly ──
        if not audio_url:
            logger.info("[merged] Stream already muxed — proxying directly")

            async def _proxy():
                async with httpx.AsyncClient(
                    timeout=DOWNLOAD_TIMEOUT,
                    follow_redirects=True,
                    headers=_HTTP_HEADERS,
                ) as client:
                    async with client.stream("GET", video_url) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_bytes(512 * 1024):
                            yield chunk

            return StreamingResponse(
                _proxy(),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="{title}.mp4"',
                    "X-Audio-Merged": "false",
                },
            )

        # ── 3. Separate streams → download + merge ──
        tmpdir = tempfile.mkdtemp(prefix="vdl_")
        video_path = os.path.join(tmpdir, "video.mp4")
        audio_path = os.path.join(tmpdir, "audio.m4a")
        output_path = os.path.join(tmpdir, "output.mp4")

        try:
            _download_file(video_url, video_path, "video")
            _download_file(audio_url, audio_path, "audio")
            _ffmpeg_merge(video_path, audio_path, output_path)
        except Exception as e:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(str(e))

        size = os.path.getsize(output_path)
        logger.info(f"[merged] Streaming {size / 1024 / 1024:.1f}MB to client")

        return StreamingResponse(
            _stream_file(output_path, tmpdir),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Content-Length": str(size),
                "X-Audio-Merged": "true",
            },
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[POST /download/merged] {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[POST /download/merged] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Merge failed unexpectedly")
