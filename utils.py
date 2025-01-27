"""
Utility functions for the YouTube scraper proxy service.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from http import HTTPStatus
from flask import jsonify

logger = logging.getLogger("proxy_scraper")

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
    Convert YouTube duration string to ISO 8601 duration format.
    E.g. "5:36" -> "PT5M36S" or "1:23:45" -> "PT1H23M45S"
    """
    parts = duration_str.split(':')
    if len(parts) == 2:  # MM:SS
        minutes, seconds = parts
        return f"PT{minutes}M{seconds}S"
    elif len(parts) == 3:  # HH:MM:SS
        hours, minutes, seconds = parts
        return f"PT{hours}H{minutes}M{seconds}S"
    return duration_str  # Return original if format not recognized 