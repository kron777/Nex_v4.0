from playwright.sync_api import sync_playwright
import time

class MoltbookInterface:

    def __init__(self):
        self.base_url = "https://moltbook.com"
        self.browser = None
        self.page = None

    def start(self):
        p = sync_playwright().start()
        self.browser = p.chromium.launch(headless=False)
        self.page = self.browser.new_page()
        self.page.goto(self.base_url)

    def login(self, username, password):
        self.page.fill("input[name='username']", username)
        self.page.fill("input[name='password']", password)
        self.page.click("button[type='submit']")
        time.sleep(3)

    def read_feed(self, limit=10):

        posts = []

        elements = self.page.query_selector_all("article")

        for e in elements[:limit]:
            try:
                text = e.inner_text()
                posts.append(text)
            except:
                pass

        return posts

    def post(self, text):

        self.page.fill("textarea", text)
        self.page.click("button[type='submit']")
        time.sleep(2)

    def reply(self, post_selector, text):

        self.page.click(post_selector)
        self.page.fill("textarea", text)
        self.page.click("button[type='submit']")
        time.sleep(2)

    def close(self):
        if self.browser:
            self.browser.close()
