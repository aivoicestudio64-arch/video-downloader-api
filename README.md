# Video Downloader API

A production-ready FastAPI backend that extracts video metadata and downloadable URLs from major social media platforms.

## Supported Platforms

| Platform    | Notes                                    |
|-------------|------------------------------------------|
| TikTok      | Public videos                            |
| Instagram   | Posts, Reels, IGTV (Instaloader + yt-dlp)|
| Facebook    | Public videos                            |
| X (Twitter) | Videos in tweets                         |
| Reddit      | v.redd.it and hosted videos              |
| Pinterest   | Video pins                               |
| Vimeo       | Public videos                            |
| Dailymotion | Public videos                            |
| Threads     | Video posts                              |
| YouTube     | Public videos                            |

---

## Project Structure

```
backend/
├── app.py                   # FastAPI application factory
├── requirements.txt         # Python dependencies
├── Dockerfile               # Production Docker image
├── .env.example             # Environment variable template
├── README.md
├── services/
│   ├── ytdlp_service.py     # yt-dlp extraction logic
│   └── instagram_service.py # Instaloader + yt-dlp fallback
├── routes/
│   ├── health.py            # GET /health
│   ├── analyze.py           # POST /analyze
│   └── download.py          # POST /download
├── models/
│   ├── requests.py          # Pydantic request schemas
│   └── responses.py         # Pydantic response schemas
└── utils/
    ├── validators.py        # URL validation + platform detection
    └── logger.py            # Structured logging setup
```

---

## Local Development

### Prerequisites

- Python 3.12+
- ffmpeg installed (`brew install ffmpeg` / `apt install ffmpeg`)

### Setup

```bash
# Clone and enter directory
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run development server
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

Interactive docs: `http://localhost:8000/docs`

---

## Docker Deployment

### Build and run locally

```bash
cd backend

docker build -t video-downloader-api .

docker run -d \
  --name video-downloader \
  -p 8000:8000 \
  --env-file .env \
  video-downloader-api
```

### Docker Compose (recommended)

```yaml
version: "3.9"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```bash
docker compose up -d
```

---

## Railway Deployment

1. Push this directory to a GitHub repository.
2. Go to [railway.app](https://railway.app) and create a new project.
3. Select **Deploy from GitHub repo** and choose your repository.
4. Set the **Root Directory** to `backend` if needed.
5. Railway will auto-detect the `Dockerfile` and build the image.
6. Add your environment variables under **Variables** tab.
7. Your API will be live at the generated Railway URL.

---

## API Reference

### GET /

Returns API status.

```bash
curl http://localhost:8000/
```

```json
{
  "status": "online",
  "version": "1.0.0"
}
```

---

### GET /health

Health check endpoint for load balancers and uptime monitors.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy"
}
```

---

### POST /analyze

Extracts full metadata and all available formats from a URL.

**Request:**
```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/@user/video/1234567890"}'
```

**Response:**
```json
{
  "success": true,
  "title": "Amazing video title",
  "thumbnail": "https://cdn.example.com/thumb.jpg",
  "duration": 30,
  "platform": "TikTok",
  "formats": [
    {
      "quality": "1080p",
      "ext": "mp4",
      "url": "https://...",
      "filesize": 10485760,
      "vcodec": "h264",
      "acodec": "aac"
    },
    {
      "quality": "720p",
      "ext": "mp4",
      "url": "https://...",
      "filesize": 5242880,
      "vcodec": "h264",
      "acodec": "aac"
    }
  ]
}
```

---

### POST /download

Returns the best single download URL for a given video.

**Request:**
```bash
curl -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://vimeo.com/123456789"}'
```

**Response:**
```json
{
  "success": true,
  "download_url": "https://cdn.vimeo.com/...",
  "platform": "Vimeo"
}
```

---

### Error Response Format

All errors follow this structure:

```json
{
  "success": false,
  "error": "Descriptive error message"
}
```

| HTTP Code | Meaning                                      |
|-----------|----------------------------------------------|
| 422       | Validation error or unsupported platform     |
| 429       | Rate limit exceeded                          |
| 500       | Internal server error                        |

---

## Environment Variables

| Variable          | Default    | Description                                    |
|-------------------|------------|------------------------------------------------|
| `APP_ENV`         | production | Environment name                               |
| `LOG_LEVEL`       | INFO       | Logging level (DEBUG, INFO, WARNING, ERROR)    |
| `LOG_FILE`        | _(empty)_  | Optional path to log file                      |
| `ALLOWED_ORIGINS` | *          | Comma-separated CORS origins                   |
| `HTTP_PROXY`      | _(empty)_  | Optional proxy for yt-dlp requests             |
| `USER_AGENT`      | Chrome UA  | Custom User-Agent for yt-dlp                   |

---

## Rate Limits

| Endpoint    | Limit       |
|-------------|-------------|
| POST /analyze  | 20 req/min |
| POST /download | 10 req/min |

---

## Security Notes

- No user credentials are stored.
- No media files are downloaded to disk.
- Only public URLs are processed.
- Input URLs are validated and platform-checked before extraction.
- CORS is configurable via `ALLOWED_ORIGINS`.
- The Docker image runs as a non-root user.
