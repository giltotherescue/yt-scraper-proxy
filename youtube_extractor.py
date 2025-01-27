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
    
def extract_channel_about_data(driver, channel_handle: str) -> Dict[str, Any]:
    """
    Navigate to the channel's /about page and extract stats from ytInitialData
    (subscriber_count, view_count, joined_date, country, etc.).
    This is more reliable than trying to click a 'More' button on the main page.
    """
    about_data = {
        'subscriber_count': None,
        'view_count': None,
        'country': None,
        'published_at': None,  # joined date
    }

    # 1) Navigate to about page
    about_url = f"https://youtube.com/{channel_handle}/about"
    driver.get(about_url)
    if not wait_for_page_load(driver, timeout=30):
        logger.warning("Channel /about page did not finish loading in 30s.")
        return about_data

    try:
        # 2) Extract the full ytInitialData from the about page
        initial_data = driver.execute_script("return window.ytInitialData;")
        if not initial_data:
            logger.warning("No ytInitialData found on /about page.")
            return about_data

        # 3) The about page typically stores stats in the 'contents.twoColumnBrowseResultsRenderer.tabs'
        #    array, under an About tab that includes 'sectionListRenderer'.
        tabs = (
            initial_data.get('contents', {})
            .get('twoColumnBrowseResultsRenderer', {})
            .get('tabs', [])
        )
        about_tab = None
        for t in tabs:
            tab_renderer = t.get('tabRenderer')
            if tab_renderer and 'about' in tab_renderer.get('endpoint', {}).get('commandMetadata', {}).get('webCommandMetadata', {}).get('url', ''):
                about_tab = tab_renderer
                break

        if not about_tab:
            logger.warning("Could not find 'About' tab in the /about page data.")
            return about_data

        section_list = about_tab.get('content', {}).get('sectionListRenderer', {})
        items = section_list.get('items', [])

        # You can find these stats typically in metadataRowContainerRenderer or similar. We'll do a quick search:
        for item in items:
            # Some channels structure data differently, so we must be flexible.
            # Usually, there's a metadataRowContainerRenderer with multiple metadataRowRenderers
            container = item.get('itemSectionRenderer', {}).get('contents', [{}])[0].get('metadataRowContainerRenderer')
            if not container:
                continue
            rows = container.get('rows', [])

            for row in rows:
                r = row.get('metadataRowRenderer', {})
                row_title = r.get('title', {}).get('simpleText', '').lower()
                row_value = r.get('contents', [{}])[0].get('simpleText', '')

                if 'joined' in row_title:  # "Joined Jan 1, 2022"
                    # attempt to parse date
                    try:
                        date_str = row_value.replace('Joined', '').strip()
                        dt = datetime.strptime(date_str, '%b %d, %Y')
                        about_data['published_at'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                elif 'views' in row_title:
                    # e.g. "1,234,567 views"
                    match = re.search(r'([\d,.]+)', row_value)
                    if match:
                        about_data['view_count'] = int(match.group(1).replace(',', ''))
                elif 'location' in row_title:
                    about_data['country'] = row_value

        # 4) Subscriber count in c4TabbedHeaderRenderer
        c4_header = (
            initial_data.get('header', {})
            .get('c4TabbedHeaderRenderer', {})
        )
        sub_count_text = c4_header.get('subscriberCountText', {}).get('simpleText', '')
        # e.g. "3.14M subscribers"
        match = re.search(r'([\d,.]+)([KMB])?\s+sub', sub_count_text, re.IGNORECASE)
        if match:
            base = float(match.group(1).replace(',', ''))
            suffix = match.group(2) or ''
            mult = {'K':1e3, 'M':1e6, 'B':1e9}.get(suffix, 1)
            about_data['subscriber_count'] = int(base * mult)

    except Exception as exc:
        logger.warning(f"Error extracting /about data: {exc}")

    return about_data


def extract_channel_metadata(driver) -> Dict[str, Any]:
    """
    Extract metadata from a YouTube channel page.
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
