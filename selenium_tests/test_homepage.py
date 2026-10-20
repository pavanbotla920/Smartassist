import unittest
import tempfile
import shutil

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class SmartAssistHomepageTest(unittest.TestCase):

    def setUp(self):
        # Create a separate temporary Firefox profile
        self.profile_dir = tempfile.mkdtemp(
            prefix="selenium-firefox-"
        )
        self.driver = None

        # Configure Firefox
        options = Options()
        options.add_argument("-headless")

        # Use the actual Firefox executable inside the Snap package
        options.binary_location = (
            "/snap/firefox/current/usr/lib/firefox/firefox"
        )

        # Use a separate profile for Selenium
        options.add_argument("-profile")
        options.add_argument(self.profile_dir)

        # Configure GeckoDriver
        service = Service(
            executable_path=(
                "/snap/firefox/current/usr/lib/firefox/geckodriver"
            ),
            log_output="geckodriver.log",
            service_args=["--log", "debug"],
        )

        # Start Firefox
        self.driver = webdriver.Firefox(
            service=service,
            options=options,
        )

        self.driver.set_window_size(1366, 768)

    def test_homepage_loads(self):
        # Open the SmartAssist-Kisan application
        self.driver.get("http://localhost:8003")

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
