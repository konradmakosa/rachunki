#!/usr/bin/env python3
"""AI audit of invoice parsers — compares parser output vs AI extraction.

Uses OpenRouter API to independently extract key fields from PDF text,
then compares with what the parser produced. Reports discrepancies.
"""

import asyncio
import hashlib
import json
import os
import sys
import glob
import time
from typing import Dict, Any, Optional

import httpx
import fitz  # PyMuPDF
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.parsers.pgnig_parser import parse_pgnig_pdf
from backend.parsers.mpwik_parser import parse_mpwik_pdf
from backend.parsers.eon_pdf_parser import parse_eon_pdf

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.0-flash-001"  # cheap, fast, good at extraction

GDRIVE_DIR = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-konrad.makosa@gmail.com/My Drive/Płatnicza/rachunki"
)

# Tolerance for numeric comparisons
COST_TOLERANCE = 1.0  # zł
CONSUMPTION_TOLERANCE = 5.0  # kWh or m³


AI_PROMPT = """Jesteś audytorem faktur. Przeanalizuj poniższy tekst wyciągnięty z faktury PDF.
Wyodrębnij TYLKO kwoty i zużycie. Odpowiedz WYŁĄCZNIE poprawnym JSON-em, bez markdown.

Pola do wyodrębnienia:
- amount_to_pay: kwota brutto do zapłaty w PLN (number, z pola "Do zapłaty" lub "Razem do zapłaty")
- cost_gross_total: łączna kwota brutto sprzedaży (number, z tabeli "Sprzedaż ogółem" / "Razem brutto" / "Wartość brutto")
- consumption_kwh: zużycie w kWh (number, dla prądu i gazu)
- consumption_m3: zużycie w m³ (number, dla gazu i wody)

Jeśli pole nie jest dostępne w tekście, ustaw null.

TEKST FAKTURY:
{text}
"""


async def call_ai(text: str, max_chars: int = 8000) -> Optional[Dict]:
    """Call OpenRouter API to extract invoice fields from text."""
    truncated = text[:max_chars]
    prompt = AI_PROMPT.format(text=truncated)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 500,
            },
        )

    if resp.status_code != 200:
        print(f"    ⚠️  API error: {resp.status_code} {resp.text[:200]}")
        return None

    content = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"    ⚠️  AI returned invalid JSON: {content[:200]}")
        return None


def extract_text(filepath: str) -> str:
    """Extract text from PDF."""
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    doc.close()
    return text


def compare_values(field: str, parser_val, ai_val, tolerance: float = 0) -> Optional[str]:
    """Compare parser vs AI value. Returns discrepancy description or None."""
    if parser_val is None and ai_val is None:
        return None
    if parser_val is None and ai_val is not None:
        return f"parser=None, AI={ai_val}"
    if parser_val is not None and ai_val is None:
        return None  # AI couldn't extract — not necessarily a bug

    # Numeric comparison
    if isinstance(parser_val, (int, float)) and isinstance(ai_val, (int, float)):
        if abs(parser_val - ai_val) > tolerance:
            return f"parser={parser_val}, AI={ai_val} (diff={abs(parser_val - ai_val):.2f})"
        return None

    # String comparison
    p = str(parser_val).strip().lower()
    a = str(ai_val).strip().lower()
    if p != a:
        return f"parser='{parser_val}', AI='{ai_val}'"
    return None


def audit_pgnig(filepath: str, parsed: Dict, ai: Dict) -> list:
    """Compare PGNiG parser output with AI extraction — amounts & consumption only."""
    issues = []
    totals = parsed.get("totals", {})
    consumption = parsed.get("consumption", {})

    checks = [
        ("amount_to_pay", parsed.get("amount_pln"), ai.get("amount_to_pay"), COST_TOLERANCE),
        ("cost_gross_total", totals.get("gross"), ai.get("cost_gross_total"), COST_TOLERANCE),
        ("consumption_kwh", consumption.get("kwh"), ai.get("consumption_kwh"), CONSUMPTION_TOLERANCE),
        ("consumption_m3", consumption.get("m3"), ai.get("consumption_m3"), CONSUMPTION_TOLERANCE),
    ]

    for name, pval, aval, tol in checks:
        disc = compare_values(name, pval, aval, tol)
        if disc:
            issues.append(f"  ❌ {name}: {disc}")

    return issues


def audit_mpwik(filepath: str, parsed: Dict, ai: Dict) -> list:
    """Compare MPWiK parser output with AI extraction — amounts & consumption only."""
    issues = []
    totals = parsed.get("totals", {})
    consumption = parsed.get("consumption", {})

    checks = [
        ("amount_to_pay", totals.get("gross") or parsed.get("amount_pln"), ai.get("amount_to_pay"), COST_TOLERANCE),
        ("cost_gross_total", totals.get("gross"), ai.get("cost_gross_total"), COST_TOLERANCE),
        ("consumption_m3", consumption.get("m3"), ai.get("consumption_m3"), CONSUMPTION_TOLERANCE),
    ]

    for name, pval, aval, tol in checks:
        disc = compare_values(name, pval, aval, tol)
        if disc:
            issues.append(f"  ❌ {name}: {disc}")

    return issues


def audit_eon(filepath: str, parsed: Dict, ai: Dict) -> list:
    """Compare e.on parser output with AI extraction — amounts & consumption only."""
    issues = []

    checks = [
        ("amount_to_pay", parsed.get("amount_pln"), ai.get("amount_to_pay"), COST_TOLERANCE),
        ("cost_gross_total", parsed.get("amount_pln"), ai.get("cost_gross_total"), COST_TOLERANCE),
        ("consumption_kwh", parsed.get("consumption", {}).get("kwh"), ai.get("consumption_kwh"), CONSUMPTION_TOLERANCE),
    ]

    for name, pval, aval, tol in checks:
        disc = compare_values(name, pval, aval, tol)
        if disc:
            issues.append(f"  ❌ {name}: {disc}")

    return issues


CACHE_PATH = os.path.join(os.path.dirname(__file__), "audit_validated.json")


def file_fingerprint(fpath: str) -> str:
    """Create a fingerprint from file path, size, and mtime."""
    stat = os.stat(fpath)
    raw = f"{fpath}|{stat.st_size}|{stat.st_mtime}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_cache() -> Dict:
    """Load validated files cache."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: Dict):
    """Save validated files cache."""
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


async def main():
    if not OPENROUTER_API_KEY:
        print("❌ Brak OPENROUTER_API_KEY w .env")
        return

    force = "--force" in sys.argv

    cache = load_cache() if not force else {}

    print("🔍 Audyt parserów faktur z użyciem AI\n")
    print(f"   Model: {MODEL}")
    print(f"   Tolerancja kosztów: ±{COST_TOLERANCE} zł")
    print(f"   Tolerancja zużycia: ±{CONSUMPTION_TOLERANCE}")
    print(f"   Cache: {len(cache)} już zwalidowanych{'  (--force: pominięty)' if force else ''}\n")

    all_issues = []
    total_checked = 0
    total_ok = 0
    total_issues = 0
    total_skipped = 0
    total_cached = 0

    # Collect all PDFs
    pdfs = []
    for provider_dir in ["pgnig", "mpwik", "eon"]:
        pattern = os.path.join(GDRIVE_DIR, provider_dir, "*.pdf")
        for fpath in sorted(glob.glob(pattern)):
            pdfs.append((provider_dir, fpath))

    print(f"📄 Znaleziono {len(pdfs)} plików PDF\n")
    print("=" * 70)

    for i, (provider, fpath) in enumerate(pdfs):
        fname = os.path.basename(fpath)
        fp = file_fingerprint(fpath)

        if fp in cache:
            total_cached += 1
            continue

        print(f"\n[{i+1}/{len(pdfs)}] {provider.upper()}: {fname}")

        # Extract text
        text = extract_text(fpath)
        if len(text.strip()) < 50:
            print("    ⏭️  Za mało tekstu (garbled PDF)")
            total_skipped += 1
            continue

        # Parse with our parser
        try:
            if provider == "pgnig":
                parsed = parse_pgnig_pdf(fpath)
            elif provider == "mpwik":
                parsed = parse_mpwik_pdf(fpath)
            elif provider == "eon":
                parsed = parse_eon_pdf(fpath)
            else:
                continue
        except Exception as e:
            print(f"    ⚠️  Parser error: {e}")
            total_skipped += 1
            continue

        # Check if parser got anything useful
        if not parsed:
            print("    ⏭️  Parser zwrócił pusty wynik")
            total_skipped += 1
            continue

        # Call AI
        ai_result = await call_ai(text)
        if not ai_result:
            total_skipped += 1
            continue

        # Compare
        if provider == "pgnig":
            issues = audit_pgnig(fpath, parsed, ai_result)
        elif provider == "mpwik":
            issues = audit_mpwik(fpath, parsed, ai_result)
        elif provider == "eon":
            issues = audit_eon(fpath, parsed, ai_result)
        else:
            issues = []

        total_checked += 1

        if issues:
            total_issues += 1
            print(f"    🔴 {len(issues)} rozbieżności:")
            for issue in issues:
                print(f"    {issue}")
            all_issues.append({"file": fname, "provider": provider, "issues": issues})
            # Don't cache files with issues — re-check after parser fix
        else:
            total_ok += 1
            print("    ✅ OK")
            # Cache validated OK files
            cache[fp] = {"file": fname, "provider": provider, "validated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            save_cache(cache)

        # Rate limiting — be nice to API
        await asyncio.sleep(0.3)

    # Summary
    print("\n" + "=" * 70)
    print("📊 PODSUMOWANIE AUDYTU\n")
    print(f"   Sprawdzono:    {total_checked}")
    print(f"   ✅ OK:          {total_ok}")
    print(f"   🔴 Rozbieżne:  {total_issues}")
    print(f"   ⏭️  Pominięte:  {total_skipped}")
    print(f"   💾 Z cache:    {total_cached}")

    if all_issues:
        print(f"\n{'=' * 70}")
        print("🔴 LISTA ROZBIEŻNOŚCI:\n")
        for item in all_issues:
            print(f"  📄 {item['provider'].upper()}: {item['file']}")
            for issue in item["issues"]:
                print(f"    {issue}")
            print()

    # Save report
    report_path = os.path.join(os.path.dirname(__file__), "audit_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": MODEL,
            "total_checked": total_checked,
            "total_ok": total_ok,
            "total_issues": total_issues,
            "total_skipped": total_skipped,
            "issues": all_issues,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Raport zapisany: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
