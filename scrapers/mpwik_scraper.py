#!/usr/bin/env python3
"""
Scraper faktur MPWiK z portalu eBOK MPWiK.

Użycie:
    python scrapers/mpwik_scraper.py [--output-dir DIR]

Skrypt:
1. Otwiera przeglądarkę Chromium
2. Czeka aż się zalogujesz ręcznie na https://ebok.mpwik.com.pl
3. Przechodzi na stronę faktur
4. Znajduje linki do PDF-ów i pobiera je
5. Zapisuje do wskazanego katalogu
"""

import argparse
import os
import time
import re
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


DEFAULT_OUTPUT_DIR = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-konrad.makosa@gmail.com"
    "/My Drive/Płatnicza/rachunki/mpwik"
)

EBOK_URL = "https://ebok.mpwik.com.pl"
INVOICES_URL = f"{EBOK_URL}/#/app/finance/invoices"


def main():
    parser = argparse.ArgumentParser(description="Scraper faktur MPWiK eBOK")
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
        user_data_dir = Path(__file__).parent / ".browser_data_mpwik"
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
    time.sleep(3)

    if not is_logged_in(page):
        print("\n🔐 Zaloguj się w otwartej przeglądarce.")
        print("   Skrypt czeka na zalogowanie (max 5 min)...")
        wait_for_login(page)

    print("✅ Zalogowano!")

    print(f"\n📋 Przechodzę na stronę faktur...")
    page.goto(INVOICES_URL, wait_until="domcontentloaded")
    time.sleep(5)

    # Paginate through all pages and collect/download invoices
    downloaded = 0
    skipped = 0
    total_found = 0
    page_num = 1

    while True:
        print(f"\n📄 Strona {page_num}...")
        time.sleep(2)

        invoices = collect_invoices(page)
        print(f"   📑 Znaleziono {len(invoices)} faktur na stronie {page_num}")
        total_found += len(invoices)

        for inv_num, attachment_url in invoices:
            safe_name = inv_num.replace("/", "_") + ".pdf"
            if safe_name.lower() in existing_files:
                print(f"   ⏭️  {inv_num} — już pobrana")
                skipped += 1
                continue

            success = download_pdf(page, inv_num, attachment_url, output_dir, safe_name)
            if success:
                downloaded += 1
                existing_files.add(safe_name.lower())

        # Try to go to next page
        next_btn = page.query_selector('a[ng-click="selectPage(page + 1, $event)"]')
        if not next_btn:
            print("   ℹ️  Brak przycisku następnej strony — koniec")
            break

        # Check if next button is disabled
        is_disabled = next_btn.get_attribute('disabled') or next_btn.get_attribute('ng-disabled')
        parent_li = next_btn.evaluate('el => el.parentElement ? el.parentElement.className : ""')
        if 'disabled' in (parent_li or ''):
            print("   ℹ️  Następna strona niedostępna — koniec")
            break

        try:
            next_btn.click(force=True)
            page_num += 1
            time.sleep(3)
        except Exception as e:
            print(f"   ℹ️  Nie udało się przejść dalej: {e}")
            break

    print(f"\n📊 Podsumowanie: pobrano {downloaded}, pominięto {skipped}, "
          f"łącznie {total_found} na {page_num} stronach")


def is_logged_in(page) -> bool:
    try:
        # MPWiK eBOK shows navbar when logged in
        page.wait_for_selector('#navbar-target, .navbar, [data-collapse="app"]', timeout=5000)
        # Also check we're not on login page
        url = page.url
        if '/login' in url:
            return False
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


def collect_invoices(page) -> list:
    """Find all invoice PDF links on the invoices page."""
    invoices = []

    # Method 1: Find direct attachment links
    links = page.query_selector_all('a[href*="getContentAsFile"]')
    if links:
        print(f"   Znaleziono {len(links)} linków do załączników")
        for link in links:
            href = link.get_attribute('href')
            if not href:
                continue
            # Make absolute URL
            if href.startswith('/'):
                href = EBOK_URL + href
            # Try to find invoice number nearby
            try:
                # Walk up to find the row/container with invoice number
                parent = link.evaluate('el => { let p = el; for(let i=0; i<10; i++) { p = p.parentElement; if(!p) break; let t = p.innerText; let m = t.match(/323520\\/\\d+/); if(m) return m[0]; } return null; }')
                inv_num = parent if parent else f"attachment_{href.split('attachmentId=')[1].split('&')[0]}"
            except Exception:
                try:
                    aid = re.search(r'attachmentId=(\d+)', href).group(1)
                    inv_num = f"attachment_{aid}"
                except Exception:
                    continue

            # Avoid duplicate invoice numbers (each invoice has 2 attachments - take first)
            if not any(inv_num == existing[0] for existing in invoices):
                invoices.append((inv_num, href))
            else:
                # Add as second attachment with suffix
                invoices.append((inv_num + "_szczegoly", href))

    # Method 2: If no direct links found, try to extract from page content
    if not invoices:
        print("   Szukam faktur w treści strony...")
        content = page.content()
        # Find all attachment URLs
        for m in re.finditer(r'attachmentId=(\d+)&amp;contextId=(\d+)&amp;wspolnotaId=(\d+)', content):
            aid, cid, wid = m.groups()
            url = f"{EBOK_URL}/ebok/attachments/getContentAsFile?attachmentId={aid}&contextId={cid}&wspolnotaId={wid}&frontAddressEvent=/app/finance/invoices"
            inv_name = f"attachment_{aid}"
            invoices.append((inv_name, url))

    return invoices


def download_pdf(page, inv_num: str, url: str, output_dir: Path, safe_name: str) -> bool:
    """Download a PDF from the given URL."""
    target_path = output_dir / safe_name

    try:
        # Clean up URL (remove &amp; artifacts)
        url = url.replace('&amp;', '&')

        response = page.request.get(url)

        if response.status == 200:
            body = response.body()
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
