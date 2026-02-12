#!/usr/bin/env python3
"""Debug: dump invoice page HTML to analyze button structure."""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

EBOK_URL = "https://ebok.myorlen.pl"
INVOICES_URL = f"{EBOK_URL}/faktury"
OUTPUT = Path(__file__).parent / "page_dump.html"

with sync_playwright() as p:
    user_data_dir = Path(__file__).parent / ".browser_data"
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=False,
        viewport={"width": 1280, "height": 900},
    )
    page = browser.pages[0] if browser.pages else browser.new_page()

    page.goto(INVOICES_URL, wait_until="domcontentloaded")
    time.sleep(5)

    # Check login
    try:
        page.wait_for_selector('[data-testid="menu/main"]', timeout=5000)
        print("✅ Zalogowany")
    except PlaywrightTimeout:
        print("🔐 Zaloguj się... czekam 60s")
        page.wait_for_selector('[data-testid="menu/main"]', timeout=60000)

    page.goto(INVOICES_URL, wait_until="domcontentloaded")
    time.sleep(5)

    # Dump the invoice list HTML
    try:
        invoice_list = page.query_selector('[data-testid="invoice/list"]')
        if invoice_list:
            html = invoice_list.inner_html()
        else:
            html = page.content()
    except Exception:
        html = page.content()

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"📄 HTML zapisany do {OUTPUT} ({len(html)} znaków)")

    # Also try clicking first invoice to see expanded state
    rows = page.query_selector_all('.invoice_element, .table-row')
    if rows:
        print(f"\n📑 Znaleziono {len(rows)} wierszy")
        rows[0].click()
        time.sleep(2)
        expanded_html = rows[0].inner_html()
        Path(OUTPUT.parent / "row_expanded.html").write_text(expanded_html, encoding="utf-8")
        print(f"📄 Rozwinięty wiersz zapisany do row_expanded.html")

        # Also dump parent
        parent_html = page.evaluate("el => el.parentElement.innerHTML", rows[0])
        Path(OUTPUT.parent / "row_parent.html").write_text(parent_html, encoding="utf-8")

    browser.close()
    print("✅ Gotowe")
