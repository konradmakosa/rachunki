"""Parser for e.on PDF invoices and forecasts."""

import re
import fitz  # PyMuPDF
from typing import Dict, Any, List, Optional


def parse_eon_pdf(filepath: str) -> Dict[str, Any]:
    """Parse an e.on PDF invoice/forecast and extract structured data."""
    doc = fitz.open(filepath)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    is_prognoza = "Prognoza zużycia" in full_text[:200]

    result = {
        "provider": "eon",
        "utility_type": "electricity",
        "raw_text": full_text,
        "doc_number": _extract_doc_number(full_text, is_prognoza),
        "doc_type": "prognoza" if is_prognoza else "faktura_rozliczeniowa",
        "issue_date": _extract_issue_date(full_text, is_prognoza),
        "location": _extract_location(full_text),
        "account_number": _extract_account_number(full_text),
        "tariff_group": _extract_tariff(full_text),
        "product": _extract_product(full_text),
    }

    if is_prognoza:
        result.update(_parse_prognoza(full_text))
    else:
        result.update(_parse_rozliczenie(full_text))

    return result


def _parse_prognoza(text: str) -> Dict[str, Any]:
    """Parse prognoza (forecast) specific data."""
    data: Dict[str, Any] = {}

    # Period
    m = re.search(r"Prognoza na okres od (\d{2}\.\d{2}\.\d{4}) do (\d{2}\.\d{2}\.\d{4})", text)
    if m:
        data["period_start"] = _date_to_iso(m.group(1))
        data["period_end"] = _date_to_iso(m.group(2))

    # Amount
    m = re.search(r"Należność\s+([\d\s,.]+)\s+płatna do\s+(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        data["amount_pln"] = _parse_number(m.group(1))
        data["due_date"] = _date_to_iso(m.group(2))

    # Consumption estimate (Dzień/Noc)
    m = re.search(r"Dzień:\s*(\d+)\s*\|\s*Noc:\s*(\d+)", text)
    if m:
        day_kwh = int(m.group(1))
        night_kwh = int(m.group(2))
        data["consumption_kwh"] = day_kwh + night_kwh
        data["consumption_day_kwh"] = day_kwh
        data["consumption_night_kwh"] = night_kwh

    # Net/gross breakdown
    m = re.search(r"Razem\s+([\d\s,.]+)\s+([\d\s,.]+)\s+([\d\s,.]+)", text)
    if m:
        data["cost_net"] = _parse_number(m.group(1))
        data["cost_vat"] = _parse_number(m.group(2))
        data["cost_gross"] = _parse_number(m.group(3))

    data["is_estimate"] = 1
    data["meter_readings"] = []
    data["cost_components"] = []

    return data


def _parse_rozliczenie(text: str) -> Dict[str, Any]:
    """Parse rozliczenie (settlement) specific data."""
    data: Dict[str, Any] = {}

    # Period
    m = re.search(
        r"[Rr]ozliczeni[ea]\s+(?:sprzedaży i dystrybucji\s+)?(?:energii elektrycznej\s+)?w okresie od\s+(\d{2}\.\d{2}\.\d{4})\s+do\s+(\d{2}\.\d{2}\.\d{4})",
        text
    )
    if m:
        data["period_start"] = _date_to_iso(m.group(1))
        data["period_end"] = _date_to_iso(m.group(2))

    # Also try: "Szczegóły rozliczenia za okres od..."
    if "period_start" not in data:
        m = re.search(
            r"za okres od\s+(\d{2}\.\d{2}\.\d{4})\s+do\s+(\d{2}\.\d{2}\.\d{4})",
            text
        )
        if m:
            data["period_start"] = _date_to_iso(m.group(1))
            data["period_end"] = _date_to_iso(m.group(2))

    # Amount - "Wartość prognozowana minus należność za faktyczne zużycie"
    # This is the credit/debit difference (newline-separated)
    m = re.search(r"Wartość prognozowana minus należność za faktyczne zużycie\n([\d\s,.]+)\n([\d\s,.]+)\n([\d\s,.]+)", text)
    if m:
        data["settlement_net"] = _parse_number(m.group(1))
        data["settlement_vat"] = _parse_number(m.group(2))
        data["settlement_gross"] = _parse_number(m.group(3))

    # Actual consumption cost (newline-separated)
    m = re.search(r"Należność za faktyczne zużycie\n([\d\s,.]+)\n23\n([\d\s,.]+)\n([\d\s,.]+)", text)
    if m:
        data["actual_cost_net"] = _parse_number(m.group(1))
        data["actual_cost_vat"] = _parse_number(m.group(2))
        data["actual_cost_gross"] = _parse_number(m.group(3))

    # Meter readings
    data["meter_readings"] = _extract_meter_readings(text)

    # Total consumption
    total_kwh = 0
    for reading in data["meter_readings"]:
        total_kwh += reading.get("consumption_kwh", 0)
    data["consumption_kwh"] = total_kwh

    # Day/night breakdown
    for reading in data["meter_readings"]:
        if reading.get("zone") == "dzienna":
            data["consumption_day_kwh"] = reading.get("consumption_kwh", 0)
        elif reading.get("zone") == "nocna":
            data["consumption_night_kwh"] = reading.get("consumption_kwh", 0)

    # Cost components
    data["cost_components"] = _extract_eon_cost_components(text)

    # Total cost from "Sprzedaż i dystrybucja energii elektrycznej"
    # Lines: Sprzedaż i dystrybucja...\nRazem\n921,66\n211,99\n1 133,65
    m = re.search(
        r"Sprzedaż i dystrybucja energii elektrycznej\nRazem\n([\d\s,.]+)\n([\d\s,.]+)\n([\d\s,.]+)",
        text
    )
    if m:
        data["cost_net"] = _parse_number(m.group(1))
        data["cost_vat"] = _parse_number(m.group(2))
        data["cost_gross"] = _parse_number(m.group(3))

    # Due date from prognozy table or main section
    m = re.search(r"płatna do\s+(\d{2}\.\d{2}\.\d{4})", text)
    if m:
        data["due_date"] = _date_to_iso(m.group(1))

    # Historical comparison
    m = re.search(
        r"aktualne zużycie energii\s+([\d\s]+)\s*kWh.*?zużycie wyniosło\s+([\d\s]+)\s*kWh",
        text, re.DOTALL
    )
    if m:
        data["current_period_kwh"] = int(m.group(1).replace(" ", ""))
        data["previous_year_kwh"] = int(m.group(2).replace(" ", ""))

    data["is_estimate"] = 0
    data["amount_pln"] = data.get("cost_gross") or data.get("settlement_gross")

    return data


def _extract_meter_readings(text: str) -> List[Dict[str, Any]]:
    """Extract meter readings from the detailed section.
    
    PDF text has data on separate lines like:
    30055830
    dzienna
    29.09.25-31.12.25
    638,83
    1 428,20
    Z
    789,37
    """
    readings = []

    # Pattern for newline-separated meter data
    # Use [^\n]+ to match single lines and avoid greedy matching across newlines
    pattern = re.compile(
        r"(\d{8})\n"
        r"(dzienna|nocna)\n"
        r"(\d{2}\.\d{2}\.\d{2})-(\d{2}\.\d{2}\.\d{2})\n"
        r"([\d ,]+[,.][\d]+)\n"
        r"([\d ,]+[,.][\d]+)\n"
        r"([RZSK])\n"
        r"([\d ,]+[,.][\d]+)"
    )

    for m in pattern.finditer(text):
        readings.append({
            "meter_number": m.group(1),
            "zone": m.group(2),
            "period_start": _short_date_to_iso(m.group(3)),
            "period_end": _short_date_to_iso(m.group(4)),
            "reading_start": _parse_number(m.group(5)),
            "reading_end": _parse_number(m.group(6)),
            "reading_type": m.group(7),
            "consumption_kwh": _parse_number(m.group(8)),
        })

    return readings


def _extract_eon_cost_components(text: str) -> List[Dict[str, Any]]:
    """Extract cost components from e.on invoice."""
    components = []

    # Pattern for cost lines like:
    # "Energia czynna\ndzienna\n29.09.25-31.12.25\n789 kWh\n0,5050\n398,45\n23\n91,64\n490,09"
    component_patterns = [
        (r"Energia czynna\s*\n\s*(dzienna|nocna)\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*kWh\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Energia czynna"),
        (r"Opłata handlowa\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*mc\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Opłata handlowa"),
        (r"Opłata jakościowa\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*kWh\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Opłata jakościowa"),
        (r"Opłata sieciowa zmienna\s*\n\s*(dzienna|nocna)\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*kWh\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Opłata sieciowa zmienna"),
        (r"Opłata sieciowa stała\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*mc\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Opłata sieciowa stała"),
        (r"Opłata mocowa\s*\n\s*[\d.]+\-[\d.]+\s*\n\s*(\d+)\s*mc\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)\s*\n\s*23\s*\n\s*([\d,]+)\s*\n\s*([\d,]+)", "Opłata mocowa"),
    ]

    # Find "Sprzedaż energii elektrycznej" and "Dystrybucja" sections
    # Lines: ...\nRazem\n566,11\n130,21\n696,32\nDystrybucja...
    m = re.search(
        r"Sprzedaż energii elektrycznej.*?Razem\n([\d\s,.]+)\n([\d\s,.]+)\n([\d\s,.]+)",
        text, re.DOTALL
    )
    if m:
        components.append({
            "name": "Sprzedaż energii elektrycznej",
            "net_amount": _parse_number(m.group(1)),
            "vat_amount": _parse_number(m.group(2)),
            "gross_amount": _parse_number(m.group(3)),
        })

    m = re.search(
        r"Dystrybucja energii elektrycznej.*?Razem\n([\d\s,.]+)\n([\d\s,.]+)\n([\d\s,.]+)",
        text, re.DOTALL
    )
    if m:
        components.append({
            "name": "Dystrybucja energii elektrycznej",
            "net_amount": _parse_number(m.group(1)),
            "vat_amount": _parse_number(m.group(2)),
            "gross_amount": _parse_number(m.group(3)),
        })

    return components


def _extract_doc_number(text: str, is_prognoza: bool) -> Optional[str]:
    if is_prognoza:
        m = re.search(r"Prognoza zużycia nr\s+(\d+)", text)
    else:
        m = re.search(r"Faktura VAT nr\s+(\d+)", text)
    return m.group(1) if m else None


def _extract_issue_date(text: str, is_prognoza: bool) -> Optional[str]:
    if is_prognoza:
        m = re.search(r"Prognoza zużycia nr\s+\d+\s+z dnia\s+(\d{2}\.\d{2}\.\d{4})", text)
    else:
        m = re.search(r"Faktura VAT nr\s+\d+\s+z dnia\s+(\d{2}\.\d{2}\.\d{4})", text)
    return _date_to_iso(m.group(1)) if m else None


def _extract_location(text: str) -> Optional[str]:
    m = re.search(r"Miejsce dostarczania energii:\s*\n?\s*(?:Warszawa,\s*)?(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return None


def _extract_account_number(text: str) -> Optional[str]:
    m = re.search(r"Konto umowy:\s*(\d+)", text)
    return m.group(1) if m else None


def _extract_tariff(text: str) -> Optional[str]:
    m = re.search(r"Grupa taryfowa:\s*(\S+)", text)
    return m.group(1) if m else None


def _extract_product(text: str) -> Optional[str]:
    m = re.search(r"Produkt:\s*(.+?)(?:\n|$)", text)
    return m.group(1).strip() if m else None


def _parse_number(s: str) -> float:
    s = s.strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _date_to_iso(date_str: str) -> str:
    parts = date_str.split(".")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _short_date_to_iso(date_str: str) -> str:
    """Convert DD.MM.YY to YYYY-MM-DD."""
    parts = date_str.split(".")
    if len(parts) == 3:
        year = int(parts[2])
        if year < 100:
            year += 2000
        return f"{year:04d}-{parts[1]}-{parts[0]}"
    return date_str
