"""AI-powered document data extraction using OpenRouter."""

import json
import httpx
import os
from typing import Dict, Any, Optional


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

EXTRACTION_PROMPT = """Jesteś ekspertem od analizy polskich faktur za media domowe (prąd, gaz, woda).
Przeanalizuj poniższy tekst wyekstrahowany z faktury/rachunku i zwróć dane w formacie JSON.

Zwróć TYLKO poprawny JSON (bez markdown, bez komentarzy) z następującą strukturą:
{
    "provider": "nazwa dostawcy (np. e.on, PGNiG, Veolia)",
    "utility_type": "electricity|gas|water|heating",
    "doc_type": "faktura_rozliczeniowa|prognoza|nota_odsetkowa",
    "doc_number": "numer dokumentu",
    "issue_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD",
    "location": "adres punktu poboru (bez 'ul.')",
    "customer_number": "numer klienta",
    "period_start": "YYYY-MM-DD (początek okresu rozliczeniowego)",
    "period_end": "YYYY-MM-DD (koniec okresu rozliczeniowego)",
    "consumption_m3": null lub liczba (zużycie w m3 dla gazu),
    "consumption_kwh": null lub liczba (zużycie w kWh),
    "meter_number": "numer licznika/gazomierza",
    "meter_reading_start": null lub liczba,
    "meter_reading_end": null lub liczba,
    "cost_net": null lub liczba (kwota netto),
    "cost_gross": null lub liczba (kwota brutto),
    "amount_to_pay": null lub liczba (do zapłaty łącznie z odsetkami),
    "is_estimate": false,
    "cost_components": [
        {
            "name": "nazwa składnika (np. Paliwo gazowe, Dystrybucyjna stała)",
            "quantity": null lub liczba,
            "unit": "kWh|m3|mc",
            "unit_price": null lub liczba,
            "vat_rate": null lub liczba,
            "net_amount": null lub liczba
        }
    ]
}

WAŻNE:
- Daty w formacie YYYY-MM-DD
- Kwoty jako liczby (nie stringi), używaj kropki jako separatora dziesiętnego
- Jeśli dokument to prognoza (nie rozliczenie rzeczywistego zużycia), ustaw is_estimate=true
- Jeśli nie możesz wyekstrahować danej wartości, ustaw null
"""


async def extract_with_ai(
    text: str,
    model: str = "google/gemini-2.0-flash-001",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Send document text to AI model via OpenRouter for structured extraction."""
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENROUTER_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": f"Tekst faktury:\n\n{text[:8000]}"},
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        )
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]

    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "Failed to parse AI response", "raw_response": content}
