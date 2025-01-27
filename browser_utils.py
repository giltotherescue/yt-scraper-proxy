"""
Browser configuration and utility functions for Selenium WebDriver.
"""

import random
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger("proxy_scraper")

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
    # Randomly select one of several modern user agents (Updated January 2024)
    user_agents = [
        # Chrome latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        
        # Firefox latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) Gecko/20100101 Firefox/122.0',
        
        # Safari latest
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
        
        # Edge latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Edg/121.0.2277.128',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Edg/121.0.2277.128',
        
        # Brave latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Brave/121.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Brave/121.0.0.0',
        
        # Opera latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 OPR/107.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 OPR/107.0.0.0',
        
        # Vivaldi latest
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Vivaldi/6.5.3206.63',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Vivaldi/6.5.3206.63',
        
        # Arc Browser (Mac only)
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Arc/1.21.1',
        
        # Yandex Browser
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 YaBrowser/24.1.0 Safari/537.36'
    ]
    chrome_options.add_argument(f'--user-agent={random.choice(user_agents)}')
    
    # Set binary location for Chromium
    chrome_options.binary_location = "/usr/bin/chromium"
    
    return chrome_options

def configure_driver_timeouts(driver: webdriver.Chrome) -> None:
    """
    Configure standard timeouts for the WebDriver instance.
    """
    driver.set_script_timeout(10)
    driver.set_page_load_timeout(20)
    driver.implicitly_wait(5)

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