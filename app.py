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
from typing import List, Dict, Any, Optional
from functools import wraps

from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

###############################################################################
# Configure Flask, CORS & Rate Limiting
###############################################################################
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per day", "10 per minute"]
)

logger = logging.getLogger("proxy_scraper")
logger.setLevel(logging.INFO)

###############################################################################
# Selenium Driver Setup (Global for Simplicity)
###############################################################################
def configure_chrome_options() -> Options:
    """
    Mirror your existing Chrome config. Headless, user-agent overrides, etc.
    For brevity, we keep it simpler than your original code. 
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
    
    # Only set binary location in production
    if not os.getenv('FLASK_ENV') == 'development':
        chrome_options.binary_location = "/usr/bin/google-chrome"
    
    # List of common browser user agents to rotate through
    user_agents = [
        # Chrome on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        # Chrome on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36',
        # Firefox on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/116.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/114.0',
        # Firefox on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/116.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/114.0',
        # Safari on Mac
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5.2 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Safari/605.1.15',
        # Edge on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.188',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.82',
        # Opera on Windows
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 OPR/101.0.0.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 OPR/100.0.0.0'
    ]
    chrome_options.add_argument(f'--user-agent={random.choice(user_agents)}')
    # Further custom settings as needed...
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
        driver = webdriver.Chrome(options=chrome_options)
        configure_driver_timeouts(driver)

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
    We'll mimic your prior scroll approach. 
    """
    start_time = time.time()
    last_count = 0
    no_change_count = 0
    max_no_change = 3
    scroll_pause_time = 2

    while True:
        # Scroll to bottom
        driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight);")
        time.sleep(scroll_pause_time)

        video_elements = driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer, ytd-grid-video-renderer")
        current_count = len(video_elements)

        if max_videos and current_count >= max_videos:
            break

        # If no new videos loaded after a few tries, stop
        if current_count == last_count:
            no_change_count += 1
            if no_change_count >= max_no_change:
                break
        else:
            no_change_count = 0

        last_count = current_count

        # If we exceed the timeout, break
        if (time.time() - start_time) > timeout:
            logger.warning("Scrolling timed out.")
            break

    # Return at most `max_videos` elements
    return driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer, ytd-grid-video-renderer")[:max_videos]

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
    Includes subscriber_count, video_count, view_count, country, banner, etc.
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

        # Attempt to click the "more" button to reveal additional stats (sub count, etc.)
        try:
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
                driver.execute_script("arguments[0].click();", more_button)
                time.sleep(2)  # wait for modal to load

                # Extract data from the modal
                modal_data = driver.execute_script("""
                    const aboutSection = document.querySelector('#additional-info-container');
                    if (!aboutSection) return null;

                    const getText = (sel) => {
                        const el = aboutSection.querySelector(sel);
                        return el ? el.textContent.trim() : null;
                    };

                    return {
                        subscribers: getText('td:has(yt-icon[icon="person_radar"]) + td'),
                        views: getText('td:has(yt-icon[icon="trending_up"]) + td'),
                        videos: getText('td:has(yt-icon[icon="my_videos"]) + td'),
                        joinDate: getText('td:has(yt-icon[icon="info_outline"]) + td'),
                        country: getText('td:has(yt-icon[icon="privacy_public"]) + td')
                    };
                """)
                if modal_data:
                    # Parse subscriber count
                    if modal_data.get('subscribers'):
                        sub_str = modal_data['subscribers']
                        # "3.1K subscribers" => "3.1K"
                        sub_val = re.split(r'\s+', sub_str)[0]
                        multiplier = 1
                        if 'K' in sub_val:
                            multiplier = 1000
                            sub_val = sub_val.replace('K', '')
                        elif 'M' in sub_val:
                            multiplier = 1000000
                            sub_val = sub_val.replace('M', '')
                        elif 'B' in sub_val:
                            multiplier = 1000000000
                            sub_val = sub_val.replace('B', '')
                        try:
                            metadata['subscriber_count'] = int(float(sub_val) * multiplier)
                        except:
                            pass

                    # Parse video count
                    if modal_data.get('videos'):
                        # e.g. "235 videos"
                        try:
                            vid_str = re.split(r'\s+', modal_data['videos'])[0].replace(',', '')
                            metadata['video_count'] = int(vid_str)
                        except:
                            pass

                    # Parse view count
                    if modal_data.get('views'):
                        # e.g. "234,567 views"
                        try:
                            view_str = re.split(r'\s+', modal_data['views'])[0].replace(',', '')
                            multi = 1
                            if 'K' in view_str:
                                multi = 1000
                                view_str = view_str.replace('K', '')
                            elif 'M' in view_str:
                                multi = 1000000
                                view_str = view_str.replace('M', '')
                            elif 'B' in view_str:
                                multi = 1000000000
                                view_str = view_str.replace('B', '')
                            metadata['view_count'] = int(float(view_str) * multi)
                        except:
                            pass

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
    Extract video ID, title, time_ago -> published_at, view_count, duration, etc.
    using JavaScript for performance (similar to your old code).
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
                const metaSpans = metadataLine?.querySelectorAll('span.inline-metadata-item, span.style-scope.ytd-video-meta-block');
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

        # Process the extracted metadata
        # 1) Published date
        published_at = get_published_date(metadata.get('time_ago', ''))

        # 2) View count
        view_count = None
        vt = metadata.get('view_count_text', '')
        match = re.search(r'([\d,.]+)([KMB]?)\s+views?', vt)
        if match:
            base = float(match.group(1).replace(',', ''))
            suffix = match.group(2)
            multi = {'K': 1e3, 'M': 1e6, 'B': 1e9, '': 1}[suffix]
            view_count = int(base * multi)

        # 3) Duration -> ISO 8601
        iso_duration = convert_duration_to_iso(metadata.get('duration', ''))

        # Construct final dictionary
        return {
            'video_id': metadata['video_id'],
            'title': metadata['title'],
            'published_at': published_at,
            'duration': iso_duration,
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
@limiter.limit("10 per minute")
@require_api_key
def scrape():
    """
    POST /scrape
    Body JSON: { "channel_handle": "@example", "max_videos": 100 }
    Returns JSON with:
    {
      "channel": {...all channel metadata...},
      "videos": [ {...}, {...} ]
    }
    """
    payload = request.json
    if not payload or 'channel_handle' not in payload:
        return jsonify({"error": "channel_handle is required"}), 400

    channel_handle = payload['channel_handle'].strip()
    max_videos = payload.get('max_videos', 100)

    # Construct channel "videos" URL
    # e.g. "https://www.youtube.com/@example/videos"
    url = f"https://youtube.com/{channel_handle}/videos"
    # If handle doesn't start with '@', we just assume "channel_handle" is the path
    # or maybe they're passing "channel/UC123..." - adapt as needed.
    logger.info(f"Scraping channel: {channel_handle} with max_videos={max_videos}")

    try:
        driver.get(url)
        if not wait_for_page_load(driver):
            return jsonify({"error": "Failed to fully load the page"}), 500

        # Extract channel-level metadata
        channel_data = extract_channel_metadata(driver)

        # Scroll to load videos
        video_elements = scroll_to_load_videos(driver, max_videos)
        logger.info(f"Found {len(video_elements)} video elements after scrolling")

        videos = []
        for elem in video_elements:
            vdata = extract_video_metadata_from_element(driver, elem)
            if vdata:
                videos.append(vdata)

        response_data = {
            "channel": channel_data,
            "videos": videos
        }
        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Scrape error: {str(e)}")
        return jsonify({"error": str(e)}), 500

###############################################################################
# Local dev entry point
###############################################################################
if __name__ == '__main__':
    # Use Flask's dev server locally, but gunicorn in production
    port = int(os.getenv('PORT', 8080))
    print('Listening on port %s' % (port))
    app.run(host='0.0.0.0', port=port, debug=True)