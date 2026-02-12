#!/usr/bin/env python3
"""
Scraper faktur PGNiG z portalu eBOK myORLEN.

Użycie:
    python scrapers/pgnig_scraper.py [--output-dir DIR]

Skrypt:
1. Otwiera przeglądarkę Chromium
2. Czeka aż się zalogujesz ręcznie na https://ebok.myorlen.pl
3. Przechodzi na stronę faktur
4. Klika "Pokaż więcej" aż załaduje wszystkie faktury
5. Dla każdej faktury klika lupę → otwiera szczegóły → pobiera PDF
6. Zapisuje do wskazanego katalogu
"""

import argparse
import os
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


DEFAULT_OUTPUT_DIR = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-konrad.makosa@gmail.com"
    "/My Drive/Płatnicza/rachunki/pgnig"
)

EBOK_URL = "https://ebok.myorlen.pl"
INVOICES_URL = f"{EBOK_URL}/faktury"


def main():
    parser = argparse.ArgumentParser(description="Scraper faktur PGNiG/myORLEN eBOK")
    parser.add_argument(
        "--output-dir", "-o",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Katalog na pobrane PDF-y (domyślnie: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Tryb headless (wymaga zapisanej sesji)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    existing_files = set(f.name.lower() for f in output_dir.glob("*.pdf"))
    print(f"📁 Katalog wyjściowy: {output_dir}")
    print(f"📄 Już pobrane pliki: {len(existing_files)}")

    with sync_playwright() as p:
        user_data_dir = Path(__file__).parent / ".browser_data"
        user_data_dir.mkdir(exist_ok=True)

        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=args.headless,
            accept_downloads=True,
            viewport={"width": 1280, "height": 900},
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        try:
            run_scraper(page, output_dir, existing_files)
        except KeyboardInterrupt:
            print("\n⏹️  Przerwano przez użytkownika")
        except Exception as e:
            print(f"\n❌ Błąd: {e}")
            raise
        finally:
            browser.close()


def run_scraper(page, output_dir: Path, existing_files: set):
    """Main scraping logic."""
    print(f"\n🌐 Otwieram {EBOK_URL}...")
    page.goto(EBOK_URL, wait_until="domcontentloaded")
    time.sleep(2)

    if not is_logged_in(page):
        print("\n🔐 Zaloguj się w otwartej przeglądarce.")
        print("   Skrypt czeka na zalogowanie (max 5 min)...")
        wait_for_login(page)

    print("✅ Zalogowano!")

    print(f"\n📋 Przechodzę na stronę faktur...")
    page.goto(INVOICES_URL, wait_until="domcontentloaded")
    time.sleep(3)

    # Wait for invoice list
    page.wait_for_selector('.invoice_element', timeout=15000)
    print("✅ Strona faktur załadowana")

    # Step 1: Click "Pokaż więcej" until all invoices are loaded
    load_all_invoices(page)

    # Step 2: Collect all invoice numbers
    invoice_nums = collect_invoice_numbers(page)
    print(f"\n📑 Znaleziono łącznie {len(invoice_nums)} faktur")

    # Step 3: For each invoice, open details and download PDF
    downloaded = 0
    skipped = 0

    for inv_num in invoice_nums:
        safe_name = inv_num.replace("/", "_") + ".pdf"
        if safe_name.lower() in existing_files:
            print(f"   ⏭️  {inv_num} — już pobrana")
            skipped += 1
            continue

        success = download_invoice_via_url(page, inv_num, output_dir, safe_name)
        if success:
            downloaded += 1
            existing_files.add(safe_name.lower())

    print(f"\n📊 Podsumowanie: pobrano {downloaded}, pominięto {skipped}, "
          f"łącznie {len(invoice_nums)}")


def is_logged_in(page) -> bool:
    try:
        page.wait_for_selector('[data-testid="menu/main"]', timeout=5000)
        return True
    except PlaywrightTimeout:
        return False


def wait_for_login(page, timeout_minutes=5):
    deadline = time.time() + timeout_minutes * 60
    dots = 0
    while time.time() < deadline:
        if is_logged_in(page):
            return
        dots = (dots + 1) % 4
        print(f"\r   Czekam{'.' * dots}{' ' * (3 - dots)}", end="", flush=True)
        time.sleep(2)
    print()
    raise TimeoutError(f"Nie zalogowano w ciągu {timeout_minutes} minut")


def load_all_invoices(page):
    """Click 'Pokaż więcej' button repeatedly to load all invoices."""
    click_count = 0
    prev_count = len(page.query_selector_all('.invoice_element'))

    while True:
        # Re-query the button each time (DOM may have changed)
        btn = page.query_selector('button#historyczne')
        if not btn:
            # Also try by text content
            btn = page.query_selector('button:has-text("Pokaż więcej")')
        if not btn:
            break
        try:
            if not btn.is_visible():
                break
        except Exception:
            break

        try:
            count_before = len(page.query_selector_all('.invoice_element'))
            print(f"   📜 Ładuję więcej faktur... (klik {click_count + 1}, obecnie {count_before} faktur)")
            btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            btn.click(force=True)
            click_count += 1
            # Wait for new invoices to appear
            time.sleep(4)
            count_after = len(page.query_selector_all('.invoice_element'))
            if count_after == count_before:
                # No new invoices loaded — try waiting a bit more
                time.sleep(3)
                count_after = len(page.query_selector_all('.invoice_element'))
                if count_after == count_before:
                    print(f"   ℹ️  Brak nowych faktur po kliknięciu — koniec")
                    break
            print(f"   📄 Załadowano {count_after - count_before} nowych faktur")
        except Exception as e:
            print(f"   ℹ️  Koniec paginacji ({e})")
            break

    total = len(page.query_selector_all('.invoice_element'))
    print(f"   ✅ Łącznie {total} faktur na stronie ({click_count} kliknięć 'Pokaż więcej')")


def collect_invoice_numbers(page) -> list:
    """Collect all invoice numbers (P/...) from the page."""
    elements = page.query_selector_all('.invoice_element')
    invoice_nums = []

    for el in elements:
        try:
            text = el.inner_text()
            # Match invoice numbers (P/...) but skip notes (NO/...)
            match = re.search(r'(P/\d+/\d+/\d+)', text)
            if match:
                invoice_nums.append(match.group(1))
        except Exception:
            pass

    return invoice_nums


def download_invoice_via_url(page, inv_num: str, output_dir: Path, safe_name: str) -> bool:
    """Download invoice PDF directly via the known URL pattern."""
    from urllib.parse import quote
    target_path = output_dir / safe_name

    # Construct the direct PDF URL
    encoded_num = quote(inv_num, safe='')
    pdf_url = f"{EBOK_URL}/crm/get-invoice-pdf?invoiceNumber={encoded_num}&mode=partial"

    try:
        # Use the page's session/cookies to fetch the PDF
        response = page.request.get(pdf_url)

        if response.status == 200:
            body = response.body()
            # Verify it's actually a PDF (starts with %PDF)
            if body[:5] == b'%PDF-':
                target_path.write_bytes(body)
                print(f"   ✅ {inv_num} → {safe_name} ({len(body) // 1024} KB)")
                return True
            else:
                print(f"   ⚠️  {inv_num} — odpowiedź nie jest PDF ({len(body)} bytes)")
                return False
        else:
            print(f"   ⚠️  {inv_num} — HTTP {response.status}")
            return False

    except Exception as e:
        print(f"   ❌ {inv_num} — błąd: {e}")
        return False


if __name__ == "__main__":
    main()
