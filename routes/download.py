from fastapi import APIRouter, HTTPException, Request
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


@router.post("/download", response_model=DownloadResponse)
@limiter.limit("10/minute")
async def download(request: Request, body: DownloadRequest):
    url = body.url
    logger.info(f"[POST /download] Received request for URL: {url}")

    is_valid, platform, error_msg = validate_url(url)
    if not is_valid:
        logger.warning(f"[POST /download] Validation failed: {error_msg}")
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
            logger.warning(f"[POST /download] No download URL found for {url}")
            raise HTTPException(
                status_code=422,
                detail="Could not extract a downloadable URL from the provided link",
            )

        logger.info(f"[POST /download] Success: platform={display_platform}")

        return DownloadResponse(
            success=True,
            download_url=download_url,
            platform=display_platform,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[POST /download] Extraction error for {url}: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"[POST /download] Unexpected error for {url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process the download request")
