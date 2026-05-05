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
import tempfile
import shutil

class SeleniumExecutor:
    def __init__(self, headless=False):
        options = webdriver.ChromeOptions()
        if headless:
            # Use the modern headless mode where available
            options.add_argument("--headless=new")

        # Optional hardening to suppress ANY password-related UI/bubbles.
        # Enable by setting STRICT_NO_PASSWORD_UI=true in the environment (.env supported via main.py)
        strict_no_pw_ui = os.getenv("STRICT_NO_PASSWORD_UI", "false").strip().lower() in {"1", "true", "yes", "on"}

        # Always launch with a clean temporary user profile so nothing persists between runs
        self._temp_user_data_dir = tempfile.mkdtemp(prefix="testflowai-chrome-")
        options.add_argument(f"--user-data-dir={self._temp_user_data_dir}")

        # Hard-disable password manager and notifications
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            # 1=allow, 2=block
            "profile.default_content_setting_values.notifications": 2,
        }

        if strict_no_pw_ui:
            # Additional prefs to aggressively suppress password/autofill/leak detection surfaces
            prefs.update(
                {
                    "credentials_enable_autosignin": False,
                    "autofill.enabled": False,
                    "autofill.profile_enabled": False,
                    "autofill.credit_card_enabled": False,
                    "autofill.address_enabled": False,
                    # Disable Safe Browsing prompts that can trigger password change suggestions
                    "safebrowsing.enabled": False,
                    "safebrowsing.scout_reporting_enabled": False,
                    # Some Chromium builds respect this key for leak detection
                    "password_manager_leak_detection": False,
                }
            )
        options.add_experimental_option("prefs", prefs)

        # Extra flags to avoid first-run prompts and similar UI noise
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        # Reduce password manager surfaces further
        options.add_argument("--disable-features=PasswordManagerOnboarding,PasswordManagerOnboardingFlow")
        options.add_argument("--disable-save-password-bubble")

        if strict_no_pw_ui:
            # Force a basic password store and disable more password/autofill features at the feature flag level
            options.add_argument("--password-store=basic")
            # Incognito sessions further suppress password save prompts and persistence
            options.add_argument("--incognito")
            options.add_argument(
                "--disable-features="
                "AutofillServerCommunication,PasswordCheck,PasswordLeakDetection,PasswordGeneration,"
                "FillOnAccountSelect,PasswordManagerOnboarding,PasswordManagerOnboardingFlow"
            )
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

    def _dismiss_transient_overlays(self):
        """Best-effort dismissal of any transient browser UI bubbles (e.g., password prompts)."""
        try:
            self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        except Exception:
            pass

    def navigate(self, url):
        if not url.startswith("http"):
            url = "https://" + url
        self.driver.get(url)
        return f"Navigated to {url}"

    def click(self, selector):
        # Attempt to clear any UI bubbles that could block the click
        self._dismiss_transient_overlays()
        element = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        element.click()
        return f"Clicked element: {selector}"

    def type_text(self, selector, text):
        element = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        element.clear()
        element.send_keys(text)
        return f"Typed '{text}' into {selector}"

    def press_key(self, key_name):
        """Press a keyboard key by name.

        Raises:
            ValueError: If the provided key name does not correspond to selenium.webdriver.common.keys.Keys
        """
        key = getattr(Keys, key_name.upper(), None)
        if not key:
            # Raise to ensure orchestrator's retry/failure logic is triggered
            raise ValueError(f"Unknown key: {key_name}")
        self.driver.switch_to.active_element.send_keys(key)
        return f"Pressed {key_name}"

    def get_page_source(self):
        # We might want to return a simplified version of the DOM to save tokens
        return self.driver.page_source

    def get_current_url(self):
        return self.driver.current_url

    def verify_text(self, text):
        # Dismiss overlays that might obscure content right before verification
        self._dismiss_transient_overlays()
        if text in self.driver.page_source:
            return f"Verification successful: '{text}' found on page"
        else:
            raise Exception(f"Verification failed: '{text}' not found on page")

    def quit(self):
        if hasattr(self, 'driver'):
            try:
                self.driver.quit()
            except Exception:
                pass
        # Clean up temporary user data directory to ensure clean profile each run
        try:
            if getattr(self, "_temp_user_data_dir", None) and os.path.isdir(self._temp_user_data_dir):
                shutil.rmtree(self._temp_user_data_dir, ignore_errors=True)
        except Exception:
            # Best-effort cleanup
            pass
