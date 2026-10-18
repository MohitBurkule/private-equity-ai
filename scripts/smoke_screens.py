"""Open every nav screen in a signed-in browser and fail on console errors or uncaught exceptions.

Run by scripts/smoke_ci.sh from `make ci`. The screen list is read from App.tsx so a new
screen is covered without editing this file. A screen that renders but logs an error
fails the run: that is how a broken load shows up before a person sees a blank page.
"""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps" / "web" / "src" / "App.tsx"


def screen_names() -> list[str]:
    names = re.findall(r'\{ id: "([^"]+)", icon', APP.read_text())
    if not names:
        raise SystemExit(f"no nav screens found in {APP}")
    return names


def on_console(msg, current: dict, failures: list[str]) -> None:
    # The browser asks for /favicon.ico on every fresh load; a missing icon is not a screen error.
    if msg.type != "error" or msg.location.get("url", "").endswith("/favicon.ico"):
        return
    failures.append(f"{current['name']}: console {msg.text} at {msg.location.get('url', '')}")


def main() -> int:
    base_url, api_key = sys.argv[1], sys.argv[2]
    failures: list[str] = []
    names = screen_names()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        current = {"name": "(sign-in)"}
        page.on("console", lambda m: on_console(m, current, failures))
        page.on("pageerror", lambda e: failures.append(f"{current['name']}: uncaught {e}"))
        page.goto(base_url)
        page.evaluate("(k) => sessionStorage.setItem('pe_api_key', k)", api_key)
        page.reload()
        page.wait_for_load_state("networkidle")
        for name in names:
            current["name"] = name
            page.locator("nav[aria-label=Sections]").get_by_role("button", name=name, exact=True).click()
            page.wait_for_load_state("networkidle")
        browser.close()
    print(f"opened {len(names)} screens")
    for line in failures:
        print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
