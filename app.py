"""
Proxy Scraper Service - A minimal Flask microservice that runs Selenium to scrape
full YouTube channel/video metadata, then returns JSON to the caller.
No database logic is included here.
"""

import json
import logging
import os
import platform
import time
from datetime import datetime
from functools import wraps
from http import HTTPStatus

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from browser_utils import (
    configure_chrome_options,
    configure_driver_timeouts,
    wait_for_page_load,
)
from utils import error_response
from youtube_extractor import (
    extract_channel_metadata,
    extract_video_metadata_from_element,
)

# Load environment variables from .env file
load_dotenv()

###############################################################################
# Configure Flask, CORS
###############################################################################
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

logger = logging.getLogger("proxy_scraper")
logger.setLevel(logging.DEBUG)

###############################################################################
# Initialize the Selenium WebDriver globally for both dev and production
###############################################################################
chrome_options = configure_chrome_options()
service = Service("/usr/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=chrome_options)
configure_driver_timeouts(driver)


@app.teardown_request
def cleanup_driver(exception=None):
    pass


###############################################################################
# Utility Functions for Metadata Extraction
###############################################################################
def scroll_to_load_videos(driver, max_videos: int, timeout: int = 60) -> list:
    """
    Scroll the channel's /videos page to load up to `max_videos` videos.
    """
    start_time = time.time()
    last_count = 0
    no_change_count = 0
    max_no_change = 3  # Number of times we'll accept no new videos before stopping
    scroll_pause_time = 2

    while True:
        # Scroll to bottom
        driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
        time.sleep(scroll_pause_time)

        # Get current video count
        video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer, ytd-grid-video-renderer")
        current_count = len(video_elements)

        # Log progress
        logger.debug(f"Found {current_count} videos...")

        # If we have enough videos, stop
        if max_videos and current_count >= max_videos:
            logger.info(f"Reached target of {max_videos} videos")
            break

        # If no new videos loaded after a few tries, stop
        if current_count == last_count:
            no_change_count += 1
            if no_change_count >= max_no_change:
                logger.info("No new videos loaded after several attempts")
                break
        else:
            no_change_count = 0

        last_count = current_count

        # If we exceed the timeout, stop
        if (time.time() - start_time) > timeout:
            logger.warning("Scrolling timed out")
            break

    # Return at most max_videos elements
    video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer, ytd-grid-video-renderer")
    return video_elements[:max_videos] if max_videos else video_elements


def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")
        if api_key and api_key == os.getenv("API_KEY"):
            return f(*args, **kwargs)
        return jsonify({"error": "Invalid API key"}), 401

    return decorated_function


###############################################################################
# Flask Endpoint
###############################################################################
@app.route("/scrape", methods=["POST"])
@require_api_key
def scrape():
    """
    POST /scrape
    Body JSON: { "channel_handle": "@example", "max_videos": 100 }
    """
    try:
        payload = request.json
        if not payload:
            return error_response("Missing JSON payload", HTTPStatus.BAD_REQUEST)

        if "channel_handle" not in payload:
            return error_response(
                "channel_handle is required in request body",
                HTTPStatus.BAD_REQUEST,
                {"required_fields": ["channel_handle"]},
            )

        channel_handle = payload["channel_handle"].strip()
        max_videos = payload.get("max_videos", 100)

        url = f"https://youtube.com/{channel_handle}/videos"
        logger.info(f"Scraping channel: {channel_handle} with max_videos={max_videos}")

        driver.get(url)
        if not wait_for_page_load(driver):
            return error_response(
                "Failed to load YouTube page",
                HTTPStatus.BAD_GATEWAY,
                {"url": url, "timeout": "30s"},
            )

        channel_data = extract_channel_metadata(driver)
        if not channel_data.get("channel_id"):
            return error_response(
                "Channel not found or is unavailable",
                HTTPStatus.NOT_FOUND,
                {"channel_handle": channel_handle},
            )

        # Scroll to load videos
        video_elements = scroll_to_load_videos(driver, max_videos)
        logger.info(f"Found {len(video_elements)} video elements after scrolling")

        if not video_elements:
            return error_response(
                "No videos found for channel",
                HTTPStatus.NOT_FOUND,
                {
                    "channel_handle": channel_handle,
                    "channel_id": channel_data.get("channel_id"),
                    "possible_reasons": [
                        "Channel has no public videos",
                        "Channel's videos tab is unavailable",
                        "YouTube layout changed",
                    ],
                },
            )

        videos = []
        failed_videos = []
        for elem in video_elements:
            try:
                vdata = extract_video_metadata_from_element(driver, elem)
                if vdata:
                    videos.append(vdata)
                else:
                    failed_videos.append(
                        {
                            "index": len(videos) + len(failed_videos),
                            "reason": "Failed to extract metadata",
                        }
                    )
            except Exception as e:
                failed_videos.append({"index": len(videos) + len(failed_videos), "reason": str(e)})

        response_data = {
            "channel": channel_data,
            "videos": videos,
            "metadata": {
                "total_videos_found": len(video_elements),
                "videos_processed": len(videos),
                "videos_failed": len(failed_videos),
                "failed_videos_details": failed_videos if failed_videos else None,
            },
        }
        return jsonify(response_data), HTTPStatus.OK

    except json.JSONDecodeError:
        return error_response("Invalid JSON in request body", HTTPStatus.BAD_REQUEST)
    except Exception as e:
        logger.error(f"Unexpected error processing request: {str(e)}")
        return error_response("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(e)})


###############################################################################
# Health Check Endpoint
###############################################################################
@app.route("/_health", methods=["GET"])
def health_check():
    """
    Health check endpoint for DigitalOcean App Platform.
    Returns basic system information and status.
    """
    try:
        # Basic system info
        health_data = {
            "status": "pass",
            "version": "1.0.0",  # You can update this with your actual version
            "timestamp": datetime.utcnow().isoformat(),
            "system": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
            },
        }

        # Check if Selenium/Chrome is working
        try:
            if driver:
                # Simple test to ensure browser is responsive
                driver.execute_script("return navigator.userAgent")
                health_data["selenium"] = "operational"
            else:
                health_data["selenium"] = "not_initialized"
        except Exception as e:
            health_data["selenium"] = f"error: {str(e)}"
            # Don't fail the health check just because Selenium has an issue
            # DO might be making frequent health checks and we don't want to
            # exhaust resources

        return jsonify(health_data), 200

    except Exception as e:
        return jsonify(
            {
                "status": "fail",
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }
        ), 500


###############################################################################
# Local dev entry point
###############################################################################
if __name__ == "__main__":
    # Use Flask's dev server locally, but gunicorn in production
    port = int(os.getenv("PORT", 8080))
    print("Listening on port %s" % (port))
    app.run(host="0.0.0.0", port=port, debug=True)
