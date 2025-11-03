# fetch_bnb_updates.py
import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright

URL_UPDATES = "https://coinmarketcap.com/cmc-ai/bnb/latest-updates/"
URL_PRICE = "https://coinmarketcap.com/currencies/bnb/"

async def get_price_variation(page):
    await page.goto(URL_PRICE, wait_until="networkidle")
    await page.wait_for_timeout(1500)
    # extract price
    price_sel = 'div.priceValue'  # this selector may change
    var_sel = 'span.sc-...percentChange24h'  # placeholder; adjust after inspecting the page
    price = await page.inner_text(price_sel)
    variation = await page.inner_text(var_sel)
    return price.strip(), variation.strip()

async def get_deep_dives(page):
    await page.goto(URL_UPDATES, wait_until="networkidle")
    await page.wait_for_timeout(2000)
    # search all blocks with the title "Deep Dive"
    deep_dives = []
    # example selector: h2 with the text Deep Dive
    headings = await page.query_selector_all("h2")
    for h in headings:
        text = await h.inner_text()
        if "Deep Dive" in text:
            # grab the next paragraph
            sibling = await h.evaluate_handle("h => h.nextElementSibling")
            if sibling:
                snippet = (await sibling.inner_text()).strip()
                deep_dives.append({"title": text.strip(), "snippet": snippet})
    return deep_dives

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        price, variation = await get_price_variation(page)
        deep_dives = await get_deep_dives(page)
        await browser.close()

    result = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "price_usd": price,
        "variation_24h": variation,
        "deep_dives": deep_dives
    }
    with open("bnb_updates.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Done — output saved to bnb_updates.json")

if __name__ == "__main__":
    asyncio.run(main())
