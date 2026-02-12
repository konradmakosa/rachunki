"""Parser for PGNiG PDF invoices."""

import re
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional


def parse_pgnig_pdf(filepath: str) -> Dict[str, Any]:
    """Parse a PGNiG PDF invoice and extract structured data.
    
    Returns dict with document info and consumption details.
    """
    doc = fitz.open(filepath)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    result = {
        "provider": "pgnig",
        "utility_type": "gas",
        "raw_text": full_text,
        "doc_number": _extract_doc_number(full_text),
        "issue_date": _extract_issue_date(full_text),
        "location": _extract_location(full_text),
        "customer_number": _extract_customer_number(full_text),
        "meter_number": _extract_meter_number(full_text),
        "amount_pln": _extract_amount(full_text),
        "due_date": _extract_due_date(full_text),
        "consumption": _extract_consumption(full_text),
        "cost_components": _extract_cost_components(full_text),
        "period": _extract_period(full_text),
        "totals": _extract_totals(full_text),
    }

    return result


def _extract_doc_number(text: str) -> Optional[str]:
    m = re.search(r"Faktura VAT nr\s+(P/\d+/\d+/\d+)", text)
    return m.group(1) if m else None


def _extract_issue_date(text: str) -> Optional[str]:
    m = re.search(r"Faktura VAT nr\s+\S+\s+z dnia\s+(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        return _date_to_iso(m.group(1))
    return None


def _extract_location(text: str) -> Optional[str]:
    m = re.search(r"Adres punktu poboru:\s*(?:Numer Klienta:\s*\d+\s*)?(ul\.\s*\S+\s+\d+)", text)
    if m:
        loc = m.group(1).replace("ul. ", "").strip()
        return loc
    return None


def _extract_customer_number(text: str) -> Optional[str]:
    m = re.search(r"Numer [Kk]lienta:\s*(\d+)", text)
    return m.group(1) if m else None


def _extract_meter_number(text: str) -> Optional[str]:
    m = re.search(r"nr gazomierza:\s*(\S+)", text)
    return m.group(1) if m else None


def _extract_amount(text: str) -> Optional[float]:
    # Collect all "Do zapłaty" and "Wartość do zapłaty" amounts, take the max
    # (partial payments reduce the amount, so the largest is the true invoice total)
    amounts = []
    for m in re.finditer(r"(?:Wartość do zapłaty|Do zapłaty):?\s*([\d ]+[,.]\d+)\s*zł", text):
        amounts.append(_parse_polish_number(m.group(1)))
    return max(amounts) if amounts else None


def _extract_due_date(text: str) -> Optional[str]:
    m = re.search(r"Termin płatności\*?:\s*(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        return _date_to_iso(m.group(1))
    return None


def _extract_consumption(text: str) -> Dict[str, Any]:
    """Extract consumption summary (m3 and kWh)."""
    result = {}

    m = re.search(r"Razem zużycie\s+(\d+)\s*\[m3\]\s+(\d+)\s*\[kWh\]", text)
    if m:
        result["m3"] = int(m.group(1))
        result["kwh"] = int(m.group(2))

    # Also try to get meter readings
    readings = re.findall(
        r"(\d+)\s+([ROS])\s+(\d+)\s+([ROS])\s+(\d+)\s*m³",
        text
    )
    if readings:
        r = readings[0]
        result["meter_start"] = int(r[0])
        result["meter_start_type"] = r[1]
        result["meter_end"] = int(r[2])
        result["meter_end_type"] = r[3]
        result["consumption_m3"] = int(r[4])

    return result


def _extract_period(text: str) -> Dict[str, Optional[str]]:
    """Extract billing period."""
    m = re.search(
        r"[Rr]ozliczeniowym\s+od\s+(\d{2}\.\d{2}\.\d{4})\s+do\s+(\d{2}\.\d{2}\.\d{4})",
        text
    )
    if m:
        return {
            "start": _date_to_iso(m.group(1)),
            "end": _date_to_iso(m.group(2)),
        }
    return {"start": None, "end": None}


def _extract_cost_components(text: str) -> List[Dict[str, Any]]:
    """Extract individual cost components from the invoice."""
    components = []

    # Opłata abonamentowa
    m = re.search(
        r"Opłata abonamentowa\s+\S+\s+[\d.]+\s+[\d.]+\s+.*?([\d,]+)\s+mc\s+([\d,]+)\s+(\d+)\s+([\d,]+)",
        text
    )
    if m:
        components.append({
            "name": "Opłata abonamentowa",
            "quantity": _parse_polish_number(m.group(1)),
            "unit": "mc",
            "unit_price": _parse_polish_number(m.group(2)),
            "vat_rate": int(m.group(3)),
            "net_amount": _parse_polish_number(m.group(4)),
        })

    # Paliwo gazowe
    m = re.search(
        r"Paliwo gazowe\s+\S+\s+\S+\s+.*?(\d+)\s*kWh\s+([\d,]+)\s+(\d+)\s+([\d\s,]+?)(?:\n|Dystrybucyjna)",
        text, re.DOTALL
    )
    if m:
        components.append({
            "name": "Paliwo gazowe",
            "quantity_kwh": int(m.group(1)),
            "unit_price": _parse_polish_number(m.group(2)),
            "vat_rate": int(m.group(3)),
            "net_amount": _parse_polish_number(m.group(4)),
        })

    # Dystrybucyjna stała - can appear multiple times
    for match in re.finditer(
        r"Dystrybucyjna stała\s+\S+\s+(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+.*?([\d,]+)\s+mc\s+([\d,]+)\s+(\d+)\s+([\d,]+)",
        text
    ):
        components.append({
            "name": "Dystrybucyjna stała",
            "period_start": _date_to_iso(match.group(1)),
            "period_end": _date_to_iso(match.group(2)),
            "quantity": _parse_polish_number(match.group(3)),
            "unit": "mc",
            "unit_price": _parse_polish_number(match.group(4)),
            "vat_rate": int(match.group(5)),
            "net_amount": _parse_polish_number(match.group(6)),
        })

    # Dystrybucyjna zmienna
    m = re.search(
        r"Dystrybucyjna zmienna\s+\S+\s+\S+\s+.*?(\d+)\s*kWh\s+([\d,]+)\s+(\d+)\s+([\d,]+)",
        text, re.DOTALL
    )
    if m:
        components.append({
            "name": "Dystrybucyjna zmienna",
            "quantity_kwh": int(m.group(1)),
            "unit_price": _parse_polish_number(m.group(2)),
            "vat_rate": int(m.group(3)),
            "net_amount": _parse_polish_number(m.group(4)),
        })

    return components


def _extract_totals(text: str) -> Dict[str, Optional[float]]:
    """Extract total amounts."""
    result = {"net": None, "vat": None, "gross": None}

    m = re.search(r"Sprzedaż ogółem\s+([\d ,]+)\s+([\d ,]+)\s+([\d ,]+)", text)
    if m:
        result["net"] = _parse_polish_number(m.group(1))
        result["vat"] = _parse_polish_number(m.group(2))
        result["gross"] = _parse_polish_number(m.group(3))

    return result


def _parse_polish_number(s: str) -> float:
    """Parse Polish number format: 1 234,56 -> 1234.56"""
    s = s.strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _date_to_iso(date_str: str) -> str:
    """Convert DD.MM.YYYY to YYYY-MM-DD."""
    parts = date_str.split(".")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str
