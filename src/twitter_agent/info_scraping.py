from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

URL = "https://coinmarketcap.com/cmc-ai/bnb/latest-updates/"
DEFAULT_OUTPUT = Path(__file__).with_name("bnb_data.json")


async def fetch_html() -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()
        return html


def parse_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    price_span = soup.select_one("span.sc-65e7f566-0.hlsqhz.base-text")
    price = price_span.get_text(strip=True) if price_span else None

    change_p = soup.select_one("p.change-text")
    variation = change_p.get_text(strip=True) if change_p else None

    deep_dives = []
    for section in soup.find_all("h2", id="deep-dive--"):
        section_block = []
        for sibling in section.find_next_siblings():
            if sibling.name == "h2":
                break
            if sibling.name in ["h3", "p"]:
                section_block.append(sibling.get_text(" ", strip=True))
        deep_dives.append("\n".join(section_block))

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "price": price,
        "variation_24h": variation,
        "deep_dives": deep_dives,
    }


async def scrape() -> dict:
    html = await fetch_html()
    return parse_data(html)


async def _save_snapshot(output_path: Path) -> dict:
    data = await scrape()
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def update_snapshot(output_path: Optional[Path] = None) -> dict:
    path = output_path or DEFAULT_OUTPUT
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_save_snapshot(path))

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_save_snapshot(path))
    finally:
        loop.close()


async def main():
    data = await _save_snapshot(DEFAULT_OUTPUT)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
