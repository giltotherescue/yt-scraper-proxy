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

1. First time setup:
    ```bash
    # Important: In Dockerfile, comment/uncomment the appropriate architecture line:

    # For M1/M2 Mac (ARM64):
    # FROM --platform=linux/arm64 python:3.10-slim-buster

    # For DigitalOcean/Production (AMD64):
    # FROM --platform=linux/amd64 python:3.10-slim-buster

    docker-compose up --build -d
    ```

2. Regular usage:
    ```bash
    # Start with live code syncing
    docker-compose up -d

    # View logs
    docker logs -f yt-scraper-proxy-container

    # Stop containers
    docker-compose down
    ```

The local setup automatically syncs your code changes thanks to volume mounting in docker-compose.yml. You don't need to rebuild the container when you make code changes - just save your files and the changes will be reflected immediately.

Note: You only need to rebuild (`--build`) if you:
- Change requirements.txt
- Modify the Dockerfile
- Need to reset the container state

## Production Build (DigitalOcean)
```
# Build

docker-compose build

# Push to DigitalOcean Container Registry

docker tag yt-scraper-proxy-scraper registry.digitalocean.com/subscribr-proxy/yt-scraper-proxy-container && docker push registry.digitalocean.com/subscribr-proxy/yt-scraper-proxy-container
```

## Deploy to DigitalOcean
[https://docs.digitalocean.com/products/container-registry/getting-started/quickstart/](Install to DigitalOcean Container Registy)


## Deploy to GCP

### Install Google Cloud CLI
[https://cloud.google.com/sdk/docs/install](Install Google Cloud CLI)

### Authenticate with Google Cloud
```bash
  gcloud auth login
```
Follow the instructions in the browser to authenticate.

### Set the project
```bash
  gcloud config set project <PROJECT_ID>
```

### Set correct environment variables in .env

- SERVER_PORT=8080 -> Port from the Dockerfile
- PROJECT_ID=your-project-id-here -> Google Cloud project ID
- GLOBAL_NAME_PREFIX=ps -> Global prefix for all resources
- SUB_NAME_PREFIX=proxy-scrapper -> Service name prefix
- ARTIFACT_REPO=${GLOBAL_NAME_PREFIX}-repo -> Artifact repository name
- REPO_REGION=us -> Artifact repository region
- REGIONS=us-east1,us-west1 -> Regions where the service will be deployed (comma separated)


### Build and push Docker image to Google Cloud
This will build the Docker image, tag it with the Google Cloud registry URL, and push it to the registry.
```bash
  sh deploy_scripts/push-to-gcp.sh
```

### Deploy to Google Cloud Run
This will deploy the service to Google Cloud Run in the regions specified in the .env file.
1 service per region will be created.
```bash
  sh deploy_scripts/deploy-to-cr.sh
```
