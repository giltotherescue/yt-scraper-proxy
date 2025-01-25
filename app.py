"""
Proxy Scraper Service - A minimal Flask microservice that runs Selenium to scrape
full YouTube channel/video metadata, then returns JSON to the caller.
No database logic is included here.
"""

import os
import json
import time
import logging
import re
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union
from functools import wraps
import platform
from http import HTTPStatus

from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from flask_cors import CORS
from dotenv import load_dotenv
from selenium.webdriver.chrome.service import Service

# Load environment variables from .env file
load_dotenv()

###############################################################################
# Configure Flask, CORS
###############################################################################
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

logger = logging.getLogger("proxy_scraper")
logger.setLevel(logging.INFO)

def error_response(message: str, status_code: int, details: Optional[Dict] = None) -> tuple[Dict[str, Any], int]:
    """
    Create a standardized error response.
    
    Args:
        message: Main error message
        status_code: HTTP status code
        details: Optional dictionary with additional error details
    
    Returns:
        Tuple of (response_dict, status_code)
    """
    response = {
        "error": {
            "message": message,
            "status_code": status_code,
            "type": HTTPStatus(status_code).phrase
        }
    }
    if details:
        response["error"]["details"] = details
    
    # Log error details
    logger.error(f"Error response: {message} ({status_code})")
    if details:
        logger.error(f"Error details: {details}")
        
    return jsonify(response), status_code

###############################################################################
# Selenium Driver Setup (Global for Simplicity)
###############################################################################
def configure_chrome_options() -> Options:
    """
    Configure Chrome options for Chromium
    """
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--mute-audio')
    chrome_options.add_argument('--autoplay-policy=user-gesture-required')
    
    # Set binary location for Chromium
    chrome_options.binary_location = "/usr/bin/chromium"
    
    return chrome_options

def configure_driver_timeouts(driver: webdriver.Chrome) -> None:
    driver.set_script_timeout(10)
    driver.set_page_load_timeout(20)
    driver.implicitly_wait(5)

# Only initialize the driver for local development
if os.getenv('FLASK_ENV') == 'development':
    chrome_options = configure_chrome_options()
    driver = webdriver.Chrome(options=chrome_options)
    configure_driver_timeouts(driver)
else:
    driver = None

@app.before_request
def setup_driver():
    """Initialize driver for each request in production"""
    if os.getenv('FLASK_ENV') != 'development':
        global driver
        chrome_options = configure_chrome_options()
        try:
            service = Service('/usr/bin/chromedriver')
            driver = webdriver.Chrome(
                service=service,
                options=chrome_options
            )
            configure_driver_timeouts(driver)
        except Exception as e:
            logger.error(f"Failed to initialize Chrome driver: {str(e)}")
            raise

@app.teardown_request
def cleanup_driver(exception=None):
    """Cleanup driver after each request in production"""
    if os.getenv('FLASK_ENV') != 'development':
        global driver
        if driver:
            driver.quit()
            driver = None

###############################################################################
# Utility Functions for Metadata Extraction
###############################################################################
def wait_for_page_load(driver, timeout: int = 30) -> bool:
    """
    Wait for the page to be fully loaded based on `document.readyState`.
    """
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                'return document.readyState === "complete" && '
                '!document.querySelector("ytd-app")?.getAttribute("is-loading")'
            )
        )
        return True
    except (TimeoutException, WebDriverException) as e:
        logger.error(f"Page load error: {str(e)}")
        return False

def scroll_to_load_videos(driver, max_videos: int, timeout: int = 60) -> List:
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

def get_published_date(time_ago_text: str) -> Optional[str]:
    """
    Convert 'time ago' text to actual date based on current time.
    E.g. "3 days ago" -> 2025-01-13 12:34:56 
    """
    try:
        match = re.search(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago', time_ago_text.lower())
        if match:
            number = int(match.group(1))
            unit = match.group(2)
            now = datetime.now()

            if unit == 'second':
                published_at = now - timedelta(seconds=number)
            elif unit == 'minute':
                published_at = now - timedelta(minutes=number)
            elif unit == 'hour':
                published_at = now - timedelta(hours=number)
            elif unit == 'day':
                published_at = now - timedelta(days=number)
            elif unit == 'week':
                published_at = now - timedelta(weeks=number)
            elif unit == 'month':
                # Approximate months as 30 days
                published_at = now - timedelta(days=number*30)
            elif unit == 'year':
                # Approximate years as 365 days
                published_at = now - timedelta(days=number*365)
            else:
                return None

            return published_at.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logger.error(f"Error parsing time_ago text: {str(e)}")
    return None

def convert_duration_to_iso(duration_str: str) -> str:
    """
    Convert duration string (e.g., "1:23:45") to ISO 8601 format "PT1H23M45S".
    """
    try:
        parts = duration_str.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return f'PT{hours}H{minutes}M{seconds}S'
        elif len(parts) == 2:
            minutes, seconds = map(int, parts)
            return f'PT{minutes}M{seconds}S'
        else:
            seconds = int(parts[0])
            return f'PT{seconds}S'
    except:
        logger.warning(f"Could not parse duration: {duration_str}")
    return 'PT0S'

def extract_channel_metadata(driver) -> Dict[str, Any]:
    """
    Extract metadata from a channel page using ytInitialData.
    """
    metadata = {
        'channel_id': None,
        'custom_url': None,
        'title': None,
        'description': None,
        'published_at': None,
        'thumbnails': {'default': {}, 'medium': {}, 'high': {}},
        'banner': {},
        'default_language': None,
        'country': None,
        'subscriber_count': None,
        'video_count': None,
        'view_count': None,
        'made_for_kids': False,
        'keywords': []
    }

    try:
        initial_data = driver.execute_script("return ytInitialData;")
        if not initial_data:
            raise ValueError("Could not find ytInitialData")

        # Channel-level data from two potential places
        header = (
            initial_data.get('metadata', {}).get('channelMetadataRenderer', {}) or
            initial_data.get('microformat', {}).get('microformatDataRenderer', {})
        )

        # Basic fields
        metadata['channel_id'] = (
            header.get('externalId') or
            header.get('channelId') or
            initial_data.get('header', {}).get('c4TabbedHeaderRenderer', {}).get('channelId')
        )
        metadata['title'] = header.get('title', '').strip()
        metadata['description'] = header.get('description', '')
        custom_url = header.get('vanityChannelUrl', '')
        if custom_url:
            # e.g. "https://youtube.com/@MyChannel"
            handle = custom_url.split('@')[-1]
            metadata['custom_url'] = '@' + handle
        else:
            # fallback if the above doesn't exist
            # parse from the current URL
            url_parts = driver.current_url.split('/')
            if len(url_parts) >= 2:
                metadata['custom_url'] = '@' + url_parts[-2].replace('@', '')

        # If header has 'keywords'
        if header.get('keywords'):
            metadata['keywords'] = [
                k.strip() for k in header['keywords'].split(',')
                if k.strip()
            ]

        # Attempt to click the "more" button to reveal additional stats
        try:
            logger.debug("Attempting to find and click 'more' button...")
            more_button = driver.execute_script("""
                return document.evaluate(
                    "//button[contains(@class, 'truncated-text-wiz__absolute-button') or "
                    + "contains(@class, 'truncated-text-wiz__inline-button')]",
                    document,
                    null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                    null
                ).singleNodeValue;
            """)
            if more_button:
                logger.debug("'More' button found, clicking...")
                driver.execute_script("arguments[0].click();", more_button)
                time.sleep(2)  # wait for modal to load
                
                logger.debug("Extracting modal data...")
                modal_data = driver.execute_script("""
                    const aboutSection = document.querySelector('#additional-info-container');
                    if (!aboutSection) return null;
                    
                    // Helper to find text next to an icon
                    const getText = (iconName) => {
                        const rows = aboutSection.querySelectorAll('tr');
                        for (const row of rows) {
                            const icon = row.querySelector(`yt-icon[icon="${iconName}"]`);
                            if (icon) {
                                const textCell = row.querySelector('td:last-child');
                                return textCell ? textCell.textContent.trim() : null;
                            }
                        }
                        return null;
                    };
                    
                    return {
                        subscribers: getText("person_radar"),
                        views: getText("trending_up"),
                        videos: getText("my_videos"),
                        joinDate: getText("info_outline"),
                        country: getText("privacy_public")
                    };
                """)
                
                if modal_data:
                    logger.debug(f"Modal data extracted: {modal_data}")

                    # Parse subscriber count
                    if modal_data.get('subscribers'):
                        sub_count = modal_data['subscribers'].split(' ')[0]  # Get "3.1K" from "3.1K subscribers"
                        multiplier = 1
                        if 'K' in sub_count:
                            multiplier = 1000
                            sub_count = sub_count.replace('K', '')
                        elif 'M' in sub_count:
                            multiplier = 1000000
                            sub_count = sub_count.replace('M', '')
                        elif 'B' in sub_count:
                            multiplier = 1000000000
                            sub_count = sub_count.replace('B', '')
                        try:
                            metadata['subscriber_count'] = int(float(sub_count) * multiplier)
                        except (ValueError, TypeError):
                            metadata['subscriber_count'] = 0

                    # Parse video count
                    if modal_data.get('videos'):
                        try:
                            video_count = modal_data['videos'].split(' ')[0].replace(',', '')
                            metadata['video_count'] = int(video_count)
                        except (ValueError, TypeError):
                            metadata['video_count'] = 0

                    # Parse view count
                    if modal_data.get('views'):
                        try:
                            view_count = modal_data['views'].split(' ')[0].replace(',', '')
                            multiplier = 1
                            if 'K' in view_count:
                                multiplier = 1000
                                view_count = view_count.replace('K', '')
                            elif 'M' in view_count:
                                multiplier = 1000000
                                view_count = view_count.replace('M', '')
                            elif 'B' in view_count:
                                multiplier = 1000000000
                                view_count = view_count.replace('B', '')
                            metadata['view_count'] = int(float(view_count) * multiplier)
                        except (ValueError, TypeError):
                            metadata['view_count'] = 0

                    # Parse country
                    if modal_data.get('country'):
                        metadata['country'] = modal_data['country']

                    # Parse join date
                    if modal_data.get('joinDate') and 'Joined' in modal_data['joinDate']:
                        try:
                            # e.g. "Joined Jan 1, 2022"
                            date_str = modal_data['joinDate'].replace('Joined', '').strip()
                            dt = datetime.strptime(date_str, '%b %d, %Y')
                            metadata['published_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            pass
        except Exception as e:
            logger.warning(f"Error getting additional metadata: {str(e)}")

        # Attempt to find channel avatar from `avatar.thumbnails`
        if 'avatar' in header and 'thumbnails' in header['avatar']:
            sorted_thumbs = sorted(header['avatar']['thumbnails'], key=lambda x: x.get('width', 0))
            if sorted_thumbs:
                # default
                def_thumb = sorted_thumbs[0]
                metadata['thumbnails']['default'] = {
                    'url': def_thumb.get('url'),
                    'width': def_thumb.get('width'),
                    'height': def_thumb.get('height')
                }
                # medium
                mid_thumb = sorted_thumbs[min(len(sorted_thumbs)-1, 1)]
                metadata['thumbnails']['medium'] = {
                    'url': mid_thumb.get('url', def_thumb.get('url')),
                    'width': mid_thumb.get('width', 240),
                    'height': mid_thumb.get('height', 240)
                }
                # high (largest)
                high_thumb = sorted_thumbs[-1]
                metadata['thumbnails']['high'] = {
                    'url': high_thumb.get('url', mid_thumb.get('url')),
                    'width': high_thumb.get('width', 800),
                    'height': high_thumb.get('height', 800)
                }

        # Attempt to find banner
        banner_url = driver.execute_script("""
            const img = document.querySelector('yt-image-banner-view-model img.yt-core-image');
            return img ? img.src : null;
        """)
        if banner_url:
            # remove trailing size query
            banner_cleaned = banner_url.split('=')[0]
            metadata['banner'] = {"bannerExternalUrl": banner_cleaned}

    except Exception as e:
        logger.error(f"Error extracting channel metadata: {str(e)}")

    return metadata

def get_video_thumbnails(video_id: str) -> Dict[str, Any]:
    """
    Generate thumbnail URLs for multiple sizes for a given video ID.
    """
    if not video_id:
        return {}
    return {
        "default": {
            "url": f"https://i.ytimg.com/vi/{video_id}/default.jpg",
            "width": 120,
            "height": 90
        },
        "medium": {
            "url": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "width": 320,
            "height": 180
        },
        "high": {
            "url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "width": 480,
            "height": 360
        }
    }

def extract_video_metadata_from_element(driver, video_element) -> Optional[Dict[str, Any]]:
    """
    Extract video metadata using JavaScript.
    """
    try:
        metadata = driver.execute_script("""
            function extractMetadata(el) {
                const link = el.querySelector('a#video-title-link, a#thumbnail');
                if (!link || !link.href) return null;
                
                const videoId = link.href.split('v=')[1]?.split('&')[0];
                if (!videoId) return null;
                
                const titleElem = el.querySelector('#video-title, #title');
                const title = titleElem?.textContent?.trim() || null;

                // Get metadata spans
                const metadataLine = el.querySelector('#metadata-line');
                const metaSpans = metadataLine?.querySelectorAll(
                    'span.inline-metadata-item, span.style-scope.ytd-video-meta-block'
                );
                let timeAgo = '';
                let viewCountText = '';

                if (metaSpans) {
                    for (const span of metaSpans) {
                        const txt = span.textContent.trim();
                        if (txt.includes('ago')) {
                            timeAgo = txt;
                        } else if (txt.includes('view')) {
                            viewCountText = txt;
                        }
                    }
                }

                // Duration
                const durationElem = el.querySelector('span#text.ytd-thumbnail-overlay-time-status-renderer');
                const duration = durationElem?.textContent?.trim() || '';

                return {
                    video_id: videoId,
                    title: title,
                    time_ago: timeAgo,
                    view_count_text: viewCountText,
                    duration: duration,
                    url: link.href
                };
            }
            return extractMetadata(arguments[0]);
        """, video_element)

        if not metadata or not metadata.get('video_id'):
            return None

        # Process view count
        view_count = None
        vt = metadata.get('view_count_text', '')
        match = re.search(r'([\d,.]+)([KMB]?)\s+views?', vt)
        if match:
            base = float(match.group(1).replace(',', ''))
            suffix = match.group(2)
            multiplier = {'K': 1e3, 'M': 1e6, 'B': 1e9, '': 1}[suffix]
            view_count = int(base * multiplier)

        # Get published date
        published_at = get_published_date(metadata.get('time_ago', ''))

        return {
            'video_id': metadata['video_id'],
            'title': metadata['title'],
            'published_at': published_at,
            'duration': convert_duration_to_iso(metadata.get('duration', '')),
            'view_count': view_count,
            'thumbnails': get_video_thumbnails(metadata['video_id']),
            'url': metadata['url']
        }
    except Exception as e:
        logger.error(f"Error extracting video metadata: {str(e)}")
        return None

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key and api_key == os.getenv('API_KEY'):
            return f(*args, **kwargs)
        return jsonify({"error": "Invalid API key"}), 401
    return decorated_function

###############################################################################
# Flask Endpoint
###############################################################################
@app.route('/scrape', methods=['POST'])
@require_api_key
def scrape():
    """
    POST /scrape
    Body JSON: { "channel_handle": "@example", "max_videos": 100 }
    """
    try:
        payload = request.json
        if not payload:
            return error_response(
                "Missing JSON payload", 
                HTTPStatus.BAD_REQUEST
            )

        if 'channel_handle' not in payload:
            return error_response(
                "channel_handle is required in request body",
                HTTPStatus.BAD_REQUEST,
                {"required_fields": ["channel_handle"]}
            )

        channel_handle = payload['channel_handle'].strip()
        max_videos = payload.get('max_videos', 100)

        url = f"https://youtube.com/{channel_handle}/videos"
        logger.info(f"Scraping channel: {channel_handle} with max_videos={max_videos}")

        try:
            driver.get(url)
            if not wait_for_page_load(driver):
                return error_response(
                    "Failed to load YouTube page",
                    HTTPStatus.BAD_GATEWAY,
                    {"url": url, "timeout": "30s"}
                )

            # Extract channel-level metadata
            channel_data = extract_channel_metadata(driver)
            if not channel_data.get('channel_id'):
                return error_response(
                    "Channel not found or is unavailable",
                    HTTPStatus.NOT_FOUND,
                    {"channel_handle": channel_handle}
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
                        "channel_id": channel_data.get('channel_id'),
                        "possible_reasons": [
                            "Channel has no public videos",
                            "Channel's videos tab is unavailable",
                            "YouTube layout changed"
                        ]
                    }
                )

            videos = []
            failed_videos = []
            for elem in video_elements:
                try:
                    vdata = extract_video_metadata_from_element(driver, elem)
                    if vdata:
                        videos.append(vdata)
                    else:
                        failed_videos.append({
                            "index": len(videos) + len(failed_videos),
                            "reason": "Failed to extract metadata"
                        })
                except Exception as e:
                    failed_videos.append({
                        "index": len(videos) + len(failed_videos),
                        "reason": str(e)
                    })

            response_data = {
                "channel": channel_data,
                "videos": videos,
                "metadata": {
                    "total_videos_found": len(video_elements),
                    "videos_processed": len(videos),
                    "videos_failed": len(failed_videos),
                    "failed_videos_details": failed_videos if failed_videos else None
                }
            }
            return jsonify(response_data), HTTPStatus.OK

        except TimeoutException:
            return error_response(
                "Request timed out while loading YouTube page",
                HTTPStatus.GATEWAY_TIMEOUT,
                {"url": url, "timeout": "30s"}
            )
        except WebDriverException as e:
            return error_response(
                "Browser automation error",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": str(e), "type": "selenium_error"}
            )
        except Exception as e:
            logger.error(f"Unexpected error during scraping: {str(e)}")
            return error_response(
                "Internal server error during scraping",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": str(e)}
            )

    except json.JSONDecodeError:
        return error_response(
            "Invalid JSON in request body",
            HTTPStatus.BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Unexpected error processing request: {str(e)}")
        return error_response(
            "Internal server error",
            HTTPStatus.INTERNAL_SERVER_ERROR,
            {"error": str(e)}
        )

###############################################################################
# Health Check Endpoint
###############################################################################
@app.route('/_health', methods=['GET'])
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
            }
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
        return jsonify({
            "status": "fail",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }), 500

###############################################################################
# Local dev entry point
###############################################################################
if __name__ == '__main__':
    # Use Flask's dev server locally, but gunicorn in production
    port = int(os.getenv('PORT', 8080))
    print('Listening on port %s' % (port))
    app.run(host='0.0.0.0', port=port, debug=True)