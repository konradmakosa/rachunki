"""Parser for MPWiK (water/sewage) PDF invoices."""

import re
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional


def parse_mpwik_pdf(filepath: str) -> Dict[str, Any]:
    """Parse an MPWiK PDF invoice and extract structured data.

    Returns dict with document info and consumption details.
    """
    doc = fitz.open(filepath)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    # Some older MPWiK PDFs have garbled text - skip those
    if not _is_readable(full_text):
        return {
            "provider": "mpwik",
            "utility_type": "water",
            "raw_text": full_text,
            "doc_number": None,
            "issue_date": None,
            "location": None,
            "amount_pln": None,
            "due_date": None,
            "consumption": {},
            "cost_components": [],
            "period": {"start": None, "end": None},
            "totals": {"net": None, "vat": None, "gross": None},
            "doc_type": "unknown",
            "is_correction": False,
            "readable": False,
        }

    is_correction = bool(re.search(r"korygując|KOR", full_text, re.IGNORECASE))

    result = {
        "provider": "mpwik",
        "utility_type": "water",
        "raw_text": full_text,
        "doc_number": _extract_doc_number(full_text),
        "issue_date": _extract_issue_date(full_text),
        "location": _extract_location(full_text),
        "amount_pln": _extract_amount(full_text),
        "due_date": _extract_due_date(full_text),
        "consumption": _extract_consumption(full_text),
        "cost_components": _extract_cost_components(full_text),
        "period": _extract_period(full_text),
        "totals": _extract_totals(full_text),
        "doc_type": "faktura_korygujaca" if is_correction else "faktura_rozliczeniowa",
        "is_correction": is_correction,
        "readable": True,
    }

    return result


def _is_readable(text: str) -> bool:
    """Check if the PDF text is readable (not garbled)."""
    # Count recognizable Polish words
    polish_words = ["Faktura", "faktura", "Nabywca", "Sprzedawca", "Termin",
                    "płatności", "wody", "ścieków", "Razem", "Brutto", "Netto"]
    found = sum(1 for w in polish_words if w in text)
    return found >= 3


def _extract_doc_number(text: str) -> Optional[str]:
    # "Faktura nr 323520/150" or "Faktura korygująca nr 323520/178/KOR"
    m = re.search(r"Faktura\s+(?:korygując[a-z]*\s+)?nr\s+(\d+/\d+(?:/KOR)?)", text)
    if m:
        return m.group(1)
    # "F-ra nr 323520/177"
    m = re.search(r"F-ra\s+nr\s+(\d+/\d+(?:/KOR)?)", text)
    return m.group(1) if m else None


def _extract_issue_date(text: str) -> Optional[str]:
    m = re.search(r"z dnia\s+(\d{2}-\d{2}-\d{4})", text)
    if m:
        return _date_to_iso(m.group(1))
    return None


def _extract_location(text: str) -> Optional[str]:
    m = re.search(r"ul\.\s+(Płatnicza\s+\d+|Rydygiera\s+\d+)", text)
    if m:
        return m.group(1).strip()
    return None


def _extract_amount(text: str) -> Optional[float]:
    # "Wartość faktury (zł):     655,30"
    m = re.search(r"Wartość faktury\s*\(zł\):\s*([\d\s]+[,.]?\d*)", text)
    if m:
        return _parse_polish_number(m.group(1))
    return None


def _extract_due_date(text: str) -> Optional[str]:
    m = re.search(r"Termin płatności:\s*(\d{2}-\d{2}-\d{4})", text)
    if m:
        return _date_to_iso(m.group(1))
    return None


def _extract_consumption(text: str) -> Dict[str, Any]:
    """Extract water consumption from meter readings."""
    result = {}

    # Look for meter reading section: "Stan początkowy ... Stan końcowy ... Zużycie"
    # Pattern: number  date  number  date  number  m3  number  number
    m = re.search(
        r"(\d+)\s+odczyt\s+(\d{2}-\d{2}-\d{4})\s+([\d,.]+)\s+(\d{2}-\d{2}-\d{4})\s+([\d,.]+)\s+m3\s+([\d,.]+)",
        text
    )
    if m:
        result["meter_number"] = m.group(1)
        result["meter_start_date"] = _date_to_iso(m.group(2))
        result["meter_start"] = _parse_polish_number(m.group(3))
        result["meter_end_date"] = _date_to_iso(m.group(4))
        result["meter_end"] = _parse_polish_number(m.group(5))
        result["consumption_m3"] = _parse_polish_number(m.group(6))

    # Fallback: look for total water quantity in line items
    # "Dostarczanie wody ... m3 ... 161,18"
    if "consumption_m3" not in result:
        m = re.search(r"Dostarczanie wody\s+m3\s+[\d-]+\s+[\d-]+\s+([\d,.]+)", text)
        if m:
            result["consumption_m3"] = _parse_polish_number(m.group(1))

    # Fallback 2: newer format with newlines between fields
    # "Dostarczenie wody - zaliczka\nrutynowa\nm3\n08-12-2025\n07-02-2026\n44,00\n..."
    if "consumption_m3" not in result:
        total_m3 = 0.0
        for m in re.finditer(
            r"Dostarcz[ea]nie wody.*?m3\s*\n\s*\d{2}-\d{2}-\d{4}\s*\n\s*\d{2}-\d{2}-\d{4}\s*\n\s*([\d,.]+)",
            text, re.DOTALL
        ):
            total_m3 += _parse_polish_number(m.group(1))
        if total_m3 > 0:
            result["consumption_m3"] = total_m3

    return result


def _extract_period(text: str) -> Dict[str, Optional[str]]:
    """Extract billing period from line items."""
    dates = []
    # Find all date ranges in line items: "DD-MM-YYYY DD-MM-YYYY"
    for m in re.finditer(r"(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s+[\d,.]+", text):
        dates.append((_date_to_iso(m.group(1)), _date_to_iso(m.group(2))))

    if dates:
        # Get the widest period
        starts = [d[0] for d in dates]
        ends = [d[1] for d in dates]
        return {"start": min(starts), "end": max(ends)}

    return {"start": None, "end": None}


def _extract_cost_components(text: str) -> List[Dict[str, Any]]:
    """Extract cost line items."""
    components = []

    # Pattern for line items:
    # "Dostarczenie wody - zaliczka rutynowa  m3  08-10-2025  07-12-2025  30,00  5,46  n  163,80  8  13,10  176,90"
    # More flexible pattern to handle multi-line names
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Check if this is a cost component line
        if any(kw in line for kw in ["Dostarczanie wody", "Dostarczenie wody", "Odprowadzanie ścieków",
                                      "zaliczka rutynowa", "rozliczenie zaliczki"]):
            # Collect the full component text (may span multiple lines)
            component_text = line
            j = i + 1
            while j < min(i + 5, len(lines)):
                next_line = lines[j].strip()
                if next_line and not any(kw in next_line for kw in
                                          ["Dostarczanie", "Dostarczenie", "Odprowadzanie", "W tym:", "Razem:"]):
                    component_text += " " + next_line
                else:
                    break
                j += 1

            # Extract values from the combined text
            # Look for: quantity  price  n/b  netto  vat%  podatek  brutto
            m = re.search(
                r"([\d,.]+)\s+([\d,.]+)\s+[nb]\s+([\d,.]+)\s+(\d+)\s+([\d,.]+)\s+([\d,.-]+)",
                component_text
            )
            if m:
                name = re.match(r"^([\w\s-]+?)(?:\s+m3|\s+\d)", component_text)
                comp_name = name.group(1).strip() if name else component_text[:50]

                components.append({
                    "name": comp_name,
                    "quantity": _parse_polish_number(m.group(1)),
                    "unit": "m3",
                    "unit_price": _parse_polish_number(m.group(2)),
                    "vat_rate": int(m.group(4)),
                    "net_amount": _parse_polish_number(m.group(3)),
                    "gross_amount": _parse_polish_number(m.group(6)),
                })

        i += 1

    return components


def _extract_totals(text: str) -> Dict[str, Optional[float]]:
    """Extract total amounts."""
    result = {"net": None, "vat": None, "gross": None}

    # "Razem:  413,70  33,10  446,80"
    m = re.search(r"Razem:\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", text)
    if m:
        result["net"] = _parse_polish_number(m.group(1))
        result["vat"] = _parse_polish_number(m.group(2))
        result["gross"] = _parse_polish_number(m.group(3))

    # Also try "Wartość faktury (zł):"
    if result["gross"] is None:
        m = re.search(r"Wartość faktury\s*\(zł\):\s*([\d\s,.]+)", text)
        if m:
            result["gross"] = _parse_polish_number(m.group(1))

    return result


def _parse_polish_number(s: str) -> float:
    """Parse Polish number format: 1 234,56 -> 1234.56"""
    s = s.strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _date_to_iso(date_str: str) -> str:
    """Convert DD-MM-YYYY or DD.MM.YYYY to YYYY-MM-DD."""
    parts = re.split(r"[.\-/]", date_str)
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str
