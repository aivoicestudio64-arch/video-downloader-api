from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from models.requests import AnalyzeRequest
from models.responses import AnalyzeResponse, FormatInfo
from services import instagram_service, ytdlp_service
from utils.logger import get_logger
from utils.validators import validate_url

logger = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["Analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("20/minute")
async def analyze(request: Request, body: AnalyzeRequest):
    url = body.url
    logger.info(f"[POST /analyze] Received request for URL: {url}")

    is_valid, platform, error_msg = validate_url(url)
    if not is_valid:
        logger.warning(f"[POST /analyze] Validation failed: {error_msg}")
        raise HTTPException(status_code=422, detail=error_msg)

    try:
        if platform == "instagram":
            data = instagram_service.extract_info(url)
        else:
            data = ytdlp_service.extract_info(url, platform)

        formats = data.get("formats", [])
        serialized_formats = []
        for fmt in formats:
            if isinstance(fmt, FormatInfo):
                serialized_formats.append(fmt)
            elif isinstance(fmt, dict):
                serialized_formats.append(FormatInfo(**fmt))

        response = AnalyzeResponse(
            success=True,
            title=data.get("title"),
            thumbnail=data.get("thumbnail"),
            duration=data.get("duration"),
            platform=data.get("platform"),
            formats=serialized_formats,
        )

        logger.info(
            f"[POST /analyze] Success: platform={response.platform}, "
            f"title='{response.title}', formats={len(serialized_formats)}"
        )
        return response

    except RuntimeError as e:
        logger.error(f"[POST /analyze] Extraction error for {url}: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[POST /analyze] Unexpected error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze the provided URL")
