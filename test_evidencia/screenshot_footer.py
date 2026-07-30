"""
Screenshot del footer con créditos usando Playwright.
"""
import asyncio
from playwright.async_api import async_playwright

API = "http://localhost:8000/api"
FRONT = "http://localhost:3000"
ADMIN_USER = "admin"
ADMIN_PASS = "Ingreso2026*"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(FRONT)
        await page.wait_for_selector("#login-username")
        await page.fill("#login-username", ADMIN_USER)
        await page.fill("#login-password", ADMIN_PASS)
        await page.click("button[onclick='login()']")
        await page.wait_for_selector("#sidebar", timeout=10000)

        # Screenshot del footer en el sidebar
        footer = page.locator("#sidebar .mt-auto")
        await footer.screenshot(path="test_evidencia/screenshot_footer_creditos.png")
        print("Screenshot guardado: test_evidencia/screenshot_footer_creditos.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
