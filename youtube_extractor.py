"""
Functions for extracting metadata from YouTube pages and elements.
"""

import re
import logging
from typing import Dict, Any, Optional
from utils import get_published_date, convert_duration_to_iso
from datetime import datetime, timedelta
from browser_utils import configure_chrome_options, configure_driver_timeouts, wait_for_page_load
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger("proxy_scraper")

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
    
def extract_channel_metadata(driver) -> Dict[str, Any]:
    """
    Extract metadata from a YouTube channel page using only the "More" modal.
    """
    logger.info("Starting channel metadata extraction...")
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
        logger.debug("Attempting to get ytInitialData...")
        initial_data = driver.execute_script("return ytInitialData;")
        if not initial_data:
            logger.error("ytInitialData not found in page")
            raise ValueError("Could not find ytInitialData")
        logger.debug("Successfully retrieved ytInitialData")

        # Channel-level data from two potential places
        header = (
            initial_data.get('metadata', {}).get('channelMetadataRenderer', {}) or
            initial_data.get('microformat', {}).get('microformatDataRenderer', {})
        )
        logger.debug(f"Found header data from: {'channelMetadataRenderer' if 'channelMetadataRenderer' in initial_data.get('metadata', {}) else 'microformatDataRenderer'}")

        # Basic fields
        channel_id = (
            header.get('externalId') or
            header.get('channelId') or
            initial_data.get('header', {}).get('c4TabbedHeaderRenderer', {}).get('channelId')
        )
        logger.debug(f"Extracted channel_id: {channel_id}")
        metadata['channel_id'] = channel_id
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

        # Attempt to click the "more" button to reveal the stats modal
        try:
            logger.info("Starting metadata extraction sequence...")
            
            # First try to find the description preview container
            logger.debug("Looking for description preview container...")
            preview_container = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR, 
                    "yt-description-preview-view-model, #description-container"
                ))
            )
            logger.debug("Found description preview container")

            # Try multiple selectors for the "more" button
            more_button = None
            button_selectors = [
                # Match the inline button
                "button.truncated-text-wiz__inline-button",
                # Match the absolute button
                "button.truncated-text-wiz__absolute-button",
                # Match by aria-label (the full label from the HTML)
                "button[aria-label*='Description'][aria-label*='tap for more']",
                # Match any button containing "...more" text
                "//button[.//span[contains(text(), '...more')]]",
                # Match by the specific classes from the HTML
                "button.truncated-text-wiz__inline-button, button.truncated-text-wiz__absolute-button",
                # Broader XPath that looks for either button
                "//button[contains(@class, 'truncated-text-wiz__') and (.//span[contains(text(), 'more')] or @aria-label[contains(., 'more')])]"
            ]

            for selector in button_selectors:
                logger.debug(f"Trying selector: {selector}")
                try:
                    if selector.startswith("//"):
                        # XPath selector
                        more_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    else:
                        # CSS selector
                        more_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                    if more_button:
                        logger.debug(f"Found 'More' button with selector: {selector}")
                        break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {str(e)}")
                    continue

            if not more_button:
                logger.warning("Could not find 'More' button with any selector")
                # Try to get metadata directly from the preview
                logger.debug("Attempting to extract metadata from preview...")
                preview_data = driver.execute_script("""
                    const container = document.querySelector('yt-description-preview-view-model, #description-container');
                    if (!container) return null;
                    
                    // Helper to find stats from the page
                    const getStats = () => {
                        const stats = {};
                        
                        // Try to get subscriber count
                        const subCount = document.querySelector('#subscriber-count');
                        if (subCount) stats.subscribers = subCount.textContent.trim();
                        
                        // Try to get video count
                        const videoCount = document.querySelector('#videos-count');
                        if (videoCount) stats.videos = videoCount.textContent.trim();
                        
                        // Try to get view count
                        const viewCount = document.querySelector('#view-count');
                        if (viewCount) stats.views = viewCount.textContent.trim();
                        
                        return stats;
                    };
                    
                    return getStats();
                """)
                
                if preview_data:
                    logger.debug(f"Found preview data: {preview_data}")
                    # Process the preview data similar to modal data
                    if preview_data.get('subscribers'):
                        # ... existing subscriber count parsing code ...
                        pass
                    # ... etc for other fields ...
                return metadata

            # If we found the more button, click it
            logger.debug("Clicking 'More' button...")
            driver.execute_script("arguments[0].click();", more_button)
            logger.debug("'More' button clicked")

            # Wait for modal or expanded content
            logger.debug("Waiting for expanded content...")
            expanded_content = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR, 
                    "#additional-info-container, #expanded-description-container"
                ))
            )
            logger.debug("Found expanded content")

            # Now parse table rows from the opened modal
            logger.debug("Executing modal data extraction script...")
            modal_data = driver.execute_script("""
                const aboutSection = document.querySelector('#additional-info-container');
                if (!aboutSection) {
                    console.log('No #additional-info-container found');
                    return null;
                }
                
                // Helper to find text next to an icon name
                const getText = (iconName) => {
                    const rows = aboutSection.querySelectorAll('tr');
                    console.log(`Searching ${rows.length} rows for icon: ${iconName}`);
                    
                    for (const row of rows) {
                        const icon = row.querySelector(`yt-icon[icon="${iconName}"]`);
                        if (icon) {
                            const textCell = row.querySelector('td:last-child');
                            const text = textCell ? textCell.textContent.trim() : null;
                            console.log(`Found ${iconName}: ${text}`);
                            return text;
                        }
                    }
                    console.log(`No row found with icon: ${iconName}`);
                    return null;
                };
                
                const data = {
                    subscribers: getText("person_radar"),
                    views: getText("trending_up"),
                    videos: getText("my_videos"),
                    joinDate: getText("info_outline"),
                    country: getText("privacy_public")
                };
                console.log('Extracted data:', data);
                return data;
            """)

            if modal_data:
                logger.info(f"Successfully extracted modal data: {modal_data}")

                # Parse subscriber count
                if modal_data.get('subscribers'):
                    logger.debug(f"Parsing subscriber count from: {modal_data['subscribers']}")
                    sub_count = modal_data['subscribers'].split(' ')[0]
                    multiplier = 1
                    if 'K' in sub_count:
                        multiplier = 1000
                        sub_count = sub_count.replace('K', '')
                        logger.debug(f"Found K multiplier, base number: {sub_count}")
                    elif 'M' in sub_count:
                        multiplier = 1_000_000
                        sub_count = sub_count.replace('M', '')
                        logger.debug(f"Found M multiplier, base number: {sub_count}")
                    elif 'B' in sub_count:
                        multiplier = 1_000_000_000
                        sub_count = sub_count.replace('B', '')
                        logger.debug(f"Found B multiplier, base number: {sub_count}")
                    
                    try:
                        final_count = int(float(sub_count) * multiplier)
                        logger.debug(f"Final subscriber count: {final_count}")
                        metadata['subscriber_count'] = final_count
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error converting subscriber count: {str(e)}")
                        metadata['subscriber_count'] = 0
                else:
                    logger.warning("No subscriber data found in modal")

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
                        view_str = modal_data['views'].split(' ')[0].replace(',', '')
                        multiplier = 1
                        if 'K' in view_str:
                            multiplier = 1000
                            view_str = view_str.replace('K', '')
                        elif 'M' in view_str:
                            multiplier = 1_000_000
                            view_str = view_str.replace('M', '')
                        elif 'B' in view_str:
                            multiplier = 1_000_000_000
                            view_str = view_str.replace('B', '')
                        metadata['view_count'] = int(float(view_str) * multiplier)
                    except (ValueError, TypeError):
                        metadata['view_count'] = 0

                # Parse country
                if modal_data.get('country'):
                    metadata['country'] = modal_data['country']

                # Parse join date
                if modal_data.get('joinDate') and 'Joined' in modal_data['joinDate']:
                    try:
                        date_str = modal_data['joinDate'].replace('Joined', '').strip()
                        dt = datetime.strptime(date_str, '%b %d, %Y')
                        metadata['published_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception as e:
                        logger.error(f"Error parsing join date: {str(e)}")
            else:
                logger.warning("Modal data extraction returned null")
                
        except Exception as e:
            logger.error(f"Error in metadata extraction: {str(e)}", exc_info=True)
            logger.error(f"Current page title: {driver.title}")
            logger.error(f"Current URL: {driver.current_url}")
            # Continue with the rest of metadata extraction even if this fails

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
        logger.error(f"Error in channel metadata extraction: {str(e)}", exc_info=True)
        
    logger.info("Channel metadata extraction completed")
    return metadata
