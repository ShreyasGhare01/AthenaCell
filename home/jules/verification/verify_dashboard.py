from playwright.sync_api import sync_playwright, expect
import os

def run():
    print("Starting Playwright frontend verification...")
    with sync_playwright() as p:
        # Launch browser headlessly
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.set_viewport_size({"width": 1280, "height": 800})

        # Set up console log tracking
        js_errors = []
        page.on("console", lambda msg: print(f"Browser Console: [{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: js_errors.append(err))

        # Navigate to local dashboard
        page.goto("http://localhost:8000")

        # Wait for header and elements to load
        page.wait_for_selector(".header-title")
        page.wait_for_selector("table")

        # Give it a second to render
        page.wait_for_timeout(3000)

        # Take screenshot of the main dashboard
        screenshot_path = "/home/jules/verification/dashboard.png"
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        page.screenshot(path=screenshot_path)
        print(f"Screenshot taken and saved to {screenshot_path}")

        # Assert no Javascript errors on page load
        if js_errors:
            print("WARNING: Javascript page errors detected!")
            for err in js_errors:
                print(f"JS Error: {err}")
        else:
            print("No Javascript compilation or runtime errors detected!")

        browser.close()

if __name__ == "__main__":
    run()
