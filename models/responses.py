from typing import List, Optional

from pydantic import BaseModel


class FormatInfo(BaseModel):
    quality: str
    ext: str
    url: str
    filesize: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    # Present when the video stream has no embedded audio.
    # The client should fetch and merge both URLs using ffmpeg.
    audio_url: Optional[str] = None


class AnalyzeResponse(BaseModel):
    success: bool
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    platform: Optional[str] = None
    formats: Optional[List[FormatInfo]] = None
    error: Optional[str] = None


class DownloadResponse(BaseModel):
    success: bool
    download_url: Optional[str] = None
    title: Optional[str] = None
    platform: Optional[str] = None
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
