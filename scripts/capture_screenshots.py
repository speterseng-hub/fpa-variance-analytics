"""Capture README screenshots of every dashboard tab.

Start the app first:  streamlit run app/streamlit_app.py
Then:                 python scripts/capture_screenshots.py [url]
Requires: pip install playwright && playwright install chromium
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
OUT = Path(__file__).resolve().parents[1] / "docs" / "img"
TABS = {"Overview": "01_overview", "Variance bridge": "02_bridge", "Country & category": "03_drilldown",
        "Forecast & scenarios": "04_forecast", "Data quality": "05_data_quality"}


def trim(path: Path, pad: int = 40) -> None:
    """Crop the empty background below the last content of the main area."""
    from PIL import Image, ImageChops
    img = Image.open(path).convert("RGB")
    w, h = img.size
    main = img.crop((int(w * 0.22), 0, w, h))
    bg = Image.new("RGB", main.size, main.getpixel((main.width - 5, h - 5)))
    box = ImageChops.difference(main, bg).point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        img.crop((0, 0, w, min(h, box[3] + pad))).save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 2300}, device_scale_factor=1.5)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("text=Management commentary", timeout=120_000)
        page.wait_for_timeout(2500)
        for tab, name in TABS.items():
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(3000)
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path))
            trim(path)
            print("saved", name)
        browser.close()


if __name__ == "__main__":
    main()
