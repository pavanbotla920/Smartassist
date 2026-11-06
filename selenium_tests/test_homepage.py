import unittest
import tempfile
import shutil
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class SmartAssistHomepageTest(unittest.TestCase):

    @staticmethod
    def _snap_geckodriver():
        candidates = sorted(
            Path("/snap/firefox").glob("*/usr/lib/firefox/geckodriver"),
            reverse=True,
        )
        for candidate in candidates:
            if os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def setUp(self):
        # Create a separate temporary browser profile.
        self.profile_dir = tempfile.mkdtemp(
            prefix="selenium-firefox-"
        )
        self.driver = None

        self.base_url = os.environ.get(
            "BASE_URL",
            "http://127.0.0.1:8003/",
        )
        browser = os.environ.get("BROWSER", "firefox").lower()

        if browser == "firefox":
            options = Options()
            options.add_argument("-headless")
            options.add_argument("-profile")
            options.add_argument(self.profile_dir)
            snap_firefox = Path("/snap/firefox/current/usr/lib/firefox/firefox")
            if snap_firefox.is_file():
                options.binary_location = str(snap_firefox)

            driver_path = os.environ.get("GECKODRIVER_PATH") or self._snap_geckodriver()
            service = Service(executable_path=driver_path) if driver_path else None
            self.driver = webdriver.Firefox(service=service, options=options)
        elif browser in {"chrome", "chromium"}:
            options = ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument(f"--user-data-dir={self.profile_dir}")
            self.driver = webdriver.Chrome(options=options)
        else:
            raise ValueError(
                f"Unsupported BROWSER={browser!r}; use firefox, chrome, or chromium."
            )

        self.driver.set_window_size(1366, 768)

    def test_homepage_loads(self):
        # Open the SmartAssist-Kisan application
        self.driver.get(self.base_url)

        # Wait for the page body to load
        WebDriverWait(self.driver, 20).until(
            EC.presence_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        # Verify the page title
        self.assertTrue(
            self.driver.title.strip(),
            "The page title should not be empty.",
        )

        # Verify that SmartAssist appears on the page
        self.assertIn(
            "SmartAssist",
            self.driver.page_source,
            "SmartAssist text was not found on the homepage.",
        )

        print("\nHomepage loaded successfully!")
        print("Page title:", self.driver.title)

    def tearDown(self):
        # Close Firefox and clean up the temporary profile
        if self.driver:
            self.driver.quit()

        if hasattr(self, "profile_dir"):
            shutil.rmtree(
                self.profile_dir,
                ignore_errors=True,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
