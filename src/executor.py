"""
Selenium executor module for TestFlowAI.
Provides a wrapper around Selenium WebDriver for executing atomic actions.
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
import os

class SeleniumExecutor:
    def __init__(self, headless=False):
        options = webdriver.ChromeOptions()
        if headless:
            # Use the modern headless mode where available
            options.add_argument("--headless=new")
        try:
            # With Selenium >= 4.6, Selenium Manager will auto-resolve the driver
            self.driver = webdriver.Chrome(options=options)
        except WebDriverException as e:
            raise RuntimeError(
                "Failed to start Chrome. Ensure Google Chrome/Chromium (or Chrome for Testing) is installed. "
                "Selenium Manager (bundled with Selenium) will handle the driver automatically. "
                f"Original error: {e}"
            )
        self.wait = WebDriverWait(self.driver, 10)

    def navigate(self, url):
        if not url.startswith("http"):
            url = "https://" + url
        self.driver.get(url)
        return f"Navigated to {url}"

    def click(self, selector):
        element = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        element.click()
        return f"Clicked element: {selector}"

    def type_text(self, selector, text):
        element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        element.clear()
        element.send_keys(text)
        return f"Typed '{text}' into {selector}"

    def press_key(self, key_name):
        key = getattr(Keys, key_name.upper(), None)
        if key:
            self.driver.switch_to.active_element.send_keys(key)
            return f"Pressed {key_name}"
        return f"Key {key_name} not found"

    def get_page_source(self):
        # We might want to return a simplified version of the DOM to save tokens
        return self.driver.page_source

    def get_current_url(self):
        return self.driver.current_url

    def verify_text(self, text):
        if text in self.driver.page_source:
            return f"Verification successful: '{text}' found on page"
        else:
            raise Exception(f"Verification failed: '{text}' not found on page")

    def quit(self):
        if hasattr(self, 'driver'):
            self.driver.quit()
