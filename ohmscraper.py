import asyncio
import json
import re
import random
from playwright.async_api import async_playwright

# Configuration for the new On-The-Go menu
CATEGORIES = [
    {"name": "ON THE GO", "url": "https://ohmtheory.com/shop/categories/on-the-go"}
]
OUTPUT_FILE = "products_ohm.json"
BASE_URL = "https://ohmtheory.com"

async def handle_age_gate(page):
    """Aggressive age gate handling for Ohm Theory"""
    print("[*] Checking for age gate...")
    try:
        # Check standard dispense and custom text buttons
        selectors = [
            'button:has-text("Yes")', 
            'button:has-text("21+")', 
            'button:has-text("I am")',
            '[data-testid="age-gate-yes-button"]',
            '.age-gate__button'
        ]
        
        for selector in selectors:
            btn = page.locator(selector)
            if await btn.is_visible(timeout=3000):
                print(f"[!] Found age gate button: {selector}. Clicking...")
                await btn.click()
                await page.wait_for_timeout(2000)
                return True
    except Exception:
        pass
    print("[*] No age gate detected or already cleared.")
    return False

async def scroll_to_load_all(page):
    """Simulates vertical scrolling to trigger infinite loading."""
    print("[*] Scrolling vertically to load all items...")
    last_height = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2500) # Give the network time to fetch new items
        
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            # Try one more small scroll to be safe
            await page.evaluate("window.scrollBy(0, -500);")
            await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            
            final_height = await page.evaluate("document.body.scrollHeight")
            if final_height == last_height:
                print("[*] Reached the bottom of the page.")
                break
        last_height = new_height

async def scrape_ohm_products(page, category_label):
    products = []
    
    # Target the specific card container from the provided HTML
    card_selector = '[data-testid="product-card-div"]'
    cards = await page.query_selector_all(card_selector)
    
    print(f"[+] Found {len(cards)} items on the page. Extracting data...")

    for card in cards:
        try:
            # 1. URL Extraction
            link_el = await card.query_selector('a[data-testid="product-card-menu-link-body"]')
            if not link_el: 
                link_el = await card.query_selector('a')
            rel_url = await link_el.get_attribute('href') if link_el else ""
            full_url = f"{BASE_URL}{rel_url}" if rel_url.startswith('/') else rel_url

            # 2. Brand and Name extraction
            brand_el = await card.query_selector('[data-testid^="product-card-brand-name"]')
            brand = (await brand_el.inner_text()).strip() if brand_el else ""
            
            name_el = await card.query_selector('[data-testid^="product-name"]')
            name = (await name_el.inner_text()).strip() if name_el else "Unknown"
            
            display_name = name
            # Clean up the name if it contains the brand and pipes (e.g., "Brand | Strain | ...")
            if brand and name.lower().startswith(brand.lower()):
                display_name = name[len(brand):]
                display_name = re.sub(r'^[\s\|\-]+', '', display_name) # Strip leading pipes/spaces

            # 3. Price Logic
            price = "$0.00"
            # Prioritize discounted price if it exists
            discount_el = await card.query_selector('[data-testid^="variant-discount-"]')
            if discount_el:
                price_text = await discount_el.inner_text()
            else:
                price_el = await card.query_selector('[data-testid^="variant-price-"]')
                price_text = await price_el.inner_text() if price_el else ""
            
            price_match = re.findall(r"\$(\d+\.?\d*)", price_text)
            if price_match:
                price = f"${price_match[-1]}" # Take the last match to avoid strikethrough original prices

            # 4. Metadata (Type + THC% + Weight)
            strain_el = await card.query_selector('[data-testid^="product-card-cannabis-type-tag-"]')
            strain = (await strain_el.inner_text()).strip() if strain_el else ""

            cannabinoid_el = await card.query_selector('[data-testid="product-card-cannabinoid-line"]')
            thc_text = ""
            if cannabinoid_el:
                cab_text = await cannabinoid_el.inner_text()
                thc_match = re.search(r"(?:THCa?|CBDa?)\s*\d+\.?\d*%", cab_text, re.IGNORECASE)
                if thc_match: 
                    thc_text = thc_match.group(0)

            weight_el = await card.query_selector('[data-testid^="variant-weight-"]')
            weight = (await weight_el.inner_text()).strip() if weight_el else ""

            # Combine available metadata into a clean string
            metadata = [m for m in [strain, thc_text, weight] if m]
            meta_display = " | ".join(metadata) if metadata else "N/A"

            # 5. Image Extraction
            img_el = await card.query_selector('img')
            img_url = await img_el.get_attribute('src') if img_el else ""

            # Ensure we only add valid products
            if name != "Unknown":
                products.append({
                    "brand": brand,
                    "name": display_name,
                    "price": price,
                    "meta": meta_display,
                    "category": category_label,
                    "image": img_url,
                    "url": full_url
                })
        except Exception as e:
            # print(f"[!] Error processing card: {e}")
            continue
            
    return products

async def main():
    async with async_playwright() as p:
        # Launching in headless mode since it's standard vertical scroll now
        browser = await p.chromium.launch(headless=True)
        
        browser_context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )

        page = await browser_context.new_page()
        all_products = []

        for category in CATEGORIES:
            print(f"\n--- Scraping {category['name']} ---")
            try:
                # Go to the category URL
                await page.goto(category['url'], wait_until="domcontentloaded", timeout=60000)
                
                # Clear the age gate
                await handle_age_gate(page)
                
                # Wait for the first product card to ensure the page has loaded
                await page.wait_for_selector('[data-testid="product-card-div"]', timeout=20000)

                # Scroll vertically to bottom
                await scroll_to_load_all(page)
                
                # Extract all data
                items = await scrape_ohm_products(page, category['name'])
                all_products.extend(items)
            except Exception as e:
                print(f"Error on {category['name']}: {e}")

        # Remove duplicates (in case scrolling caught the same items twice) and shuffle
        unique_products = list({p['name']+p['brand']: p for p in all_products}.values())
        random.shuffle(unique_products)
        
        # Save to JSON
        with open(OUTPUT_FILE, "w") as f:
            json.dump(unique_products, f, indent=4)
        
        print(f"\n[✔] Success! Saved {len(unique_products)} products to {OUTPUT_FILE}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())