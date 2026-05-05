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
from typing import List

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

    # ===== Structured verification methods =====

    def _xpath_literal(self, s: str) -> str:
        """Return an XPath string literal that safely represents s.

        Handles both single and double quotes by using concat() when needed.
        """
        if '"' not in s:
            return f'"{s}"'
        if "'" not in s:
            return f"'{s}'"
        parts = []
        for part in s.split('"'):
            if part:
                parts.append(f'"{part}"')
            parts.append("'\"'")  # add a literal double quote character
        if parts and parts[-1] == "'\"'":
            parts.pop()
        return "concat(" + ", ".join(parts) + ")"

    def verify_contains_text_page(self, expected: str):
        self._dismiss_transient_overlays()
        xp = f"//*[contains(normalize-space(string(.)), {self._xpath_literal(expected)})]"
        try:
            self.wait.until(lambda d: len(d.find_elements(By.XPATH, xp)) > 0)
            return f"Verification successful: page contains text '{expected}'"
        except Exception:
            # Fallback to page_source for diagnostics only
            page_contains = expected in (self.driver.page_source or "")
            actual = "found in page_source" if page_contains else "not found"
            raise AssertionError(
                f"contains_text failed: expected='{expected}', actual={actual}"
            )

    def verify_equals_text_page(self, expected: str):
        self._dismiss_transient_overlays()
        xp = f"//*[normalize-space(string(.)) = {self._xpath_literal(expected.strip())}]"
        try:
            self.wait.until(lambda d: len(d.find_elements(By.XPATH, xp)) > 0)
            return f"Verification successful: page has an element with exact text '{expected}'"
        except Exception:
            raise AssertionError(
                f"equals_text failed: expected='{expected}', actual='no exact match on page'"
            )

    def verify_element_visible(self, selector: str):
        try:
            el = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
            # Optionally ensure enabled/clickable? Visibility is enough per spec.
            return f"Verification successful: element visible '{selector}'"
        except Exception:
            raise AssertionError(
                f"element_visible failed: selector='{selector}', actual='not visible'"
            )

    def verify_element_count(self, selector: str, expected_count: int):
        try:
            self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, selector)) == int(expected_count))
            return f"Verification successful: count({selector}) == {expected_count}"
        except Exception:
            actual = len(self.driver.find_elements(By.CSS_SELECTOR, selector))
            raise AssertionError(
                f"element_count failed: selector='{selector}', expected={expected_count}, actual={actual}"
            )

    def verify_element_text_contains(self, selector: str, expected: str):
        try:
            def any_contains(d) -> bool:
                els: List = d.find_elements(By.CSS_SELECTOR, selector)
                for el in els:
                    try:
                        if expected in (el.text or ""):
                            return True
                    except Exception:
                        continue
                return False

            self.wait.until(any_contains)
            return f"Verification successful: element '{selector}' contains text '{expected}'"
        except Exception:
            # Collect a small sample of actual text for diagnostics
            els = self.driver.find_elements(By.CSS_SELECTOR, selector)
            sample = " | ".join([(e.text or "").strip() for e in els[:3]])
            raise AssertionError(
                f"contains_text failed: selector='{selector}', expected='{expected}', actual_sample='{sample}'"
            )

    def verify_element_text_equals(self, selector: str, expected: str):
        try:
            def any_equals(d) -> bool:
                els: List = d.find_elements(By.CSS_SELECTOR, selector)
                for el in els:
                    try:
                        if (el.text or "") == expected:
                            return True
                    except Exception:
                        continue
                return False

            self.wait.until(any_equals)
            return f"Verification successful: element '{selector}' has exact text '{expected}'"
        except Exception:
            els = self.driver.find_elements(By.CSS_SELECTOR, selector)
            sample = " | ".join([(e.text or "").strip() for e in els[:3]])
            raise AssertionError(
                f"equals_text failed: selector='{selector}', expected='{expected}', actual_sample='{sample}'"
            )

    def verify_url_contains(self, expected_substring: str):
        try:
            self.wait.until(EC.url_contains(expected_substring))
            return f"Verification successful: url contains '{expected_substring}'"
        except Exception:
            actual = self.driver.current_url
            raise AssertionError(
                f"url_contains failed: expected_substring='{expected_substring}', actual_url='{actual}'"
            )

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
