# YouTube Scraper Proxy

A Flask microservice that scrapes YouTube channel metadata and video information. Returns clean JSON data through a simple API endpoint.

## Features

- Scrapes channel info (subscribers, views, description, etc.)
- Scrapes video details (titles, views, durations, etc.)
- Returns everything as structured JSON
- Handles rate limiting and authentication
- Uses rotating user agents to avoid blocks

## Setup

### Local Development

1. Clone this repository
2. Install Python requirements from requirements.txt
3. Copy .env.example to .env and add your API key
4. Run main.py

### DigitalOcean Deployment

1. Push code to GitHub
2. Go to DigitalOcean Apps dashboard
3. Create new app -> Select your repo
4. Add environment variable:
   - Key: `API_KEY`
   - Value: Your secret key
5. Deploy!

## API Documentation

### Scrape Channel Data

**Endpoint:** POST /scrape

**Required Headers:**
- Content-Type: application/json  
- X-API-Key: Your API key

**Request Body Parameters:**
- channel_handle: YouTube channel handle (e.g. @channelname)
- max_videos: Maximum number of videos to scrape (optional, default 100)

**Response Data:**
- channel: Channel metadata (id, title, subscribers, etc)
- videos: Array of video data (titles, views, durations, etc)

## Limits & Security

### Rate Limits
- 100 requests per day
- 10 requests per minute

### Security Features
- API key authentication required
- Rate limiting enabled
- User agent rotation
- Headless browser operation

## Files

- app.py - Core application (Flask)
- gunicorn_config.py - Gunicorn server configuration
- requirements.txt - Python dependencies
- .env - Environment variables (not in git)
- app.yaml - DigitalOcean App Platform config
- Procfile - Process configuration
- .gitignore - Git ignore rules


# Docker

## Local Development (M1/M2 Mac)
Run: `docker-compose -f docker-compose.local.yml up -d`
Stop: `docker-compose -f docker-compose.local.yml down`
Rebuild: `docker-compose -f docker-compose.local.yml up --build -d`
Logs: `docker logs -f yt-scraper-proxy-container`

## Production Build (DigitalOcean)
Run: `docker-compose up -d`
Stop: `docker-compose down`
Rebuild: `docker-compose up --build -d`
Logs: `docker logs -f yt-scraper-proxy-container`

## Deploy to DigitalOcean
[https://docs.digitalocean.com/products/container-registry/getting-started/quickstart/](Install to DigitalOcean Container Registy)

```
docker tag yt-scraper-proxy-scraper registry.digitalocean.com/subscribr-proxy/yt-scraper-proxy-container
docker push registry.digitalocean.com/subscribr-proxy/yt-scraper-proxy-container
```

```

Key differences in the local setup:
1. Uses `platform: linux/arm64` for M2 Mac
2. Mounts the local directory as a volume for live code updates
3. Same functionality but optimized for local ARM architecture

Now you can:
- Use `docker-compose.yml` for production (AMD64)
- Use `docker-compose.local.yml` for local development (ARM64)
- Keep the Dockerfile as is with AMD64 for production deployments