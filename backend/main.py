"""Main FastAPI application for utility bill analysis."""

import os
import shutil
import glob
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from backend.database import init_db, get_db
from backend.parsers.eon_parser import parse_eon_xlsx, extract_eon_consumption
from backend.parsers.eon_pdf_parser import parse_eon_pdf
from backend.parsers.pgnig_parser import parse_pgnig_pdf
from backend.parsers.mpwik_parser import parse_mpwik_pdf
from backend.ai_extractor import extract_with_ai

load_dotenv()

app = FastAPI(title="Rachunki - Analiza Mediów Domowych")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
GDRIVE_DIR = os.getenv(
    "GDRIVE_RACHUNKI_DIR",
    os.path.expanduser(
        "~/Library/CloudStorage/GoogleDrive-konrad.makosa@gmail.com/My Drive/Płatnicza/rachunki"
    ),
)


@app.on_event("startup")
async def startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    await init_db()


# ── API Routes ──────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a document (PDF, XLSX, MHTML) for processing."""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".xlsx", ".mhtml", ".html"):
        raise HTTPException(400, f"Unsupported file type: {ext}")

    filepath = os.path.join(UPLOAD_DIR, file.filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"filename": file.filename, "path": filepath, "size": os.path.getsize(filepath)}


@app.post("/api/scan-gdrive")
async def scan_gdrive():
    """Scan Google Drive directory for new documents."""
    if not os.path.isdir(GDRIVE_DIR):
        raise HTTPException(404, f"Google Drive directory not found: {GDRIVE_DIR}")

    found = []
    for pattern in ("**/*.pdf", "**/*.xlsx", "**/*.mhtml"):
        for fpath in glob.glob(os.path.join(GDRIVE_DIR, pattern), recursive=True):
            found.append({
                "filename": os.path.basename(fpath),
                "path": fpath,
                "size": os.path.getsize(fpath),
                "provider": _guess_provider(fpath),
            })

    return {"files": found, "directory": GDRIVE_DIR}


@app.post("/api/process")
async def process_file(filepath: str, use_ai: bool = False):
    """Process a document file - parse and store in database."""
    if not os.path.isfile(filepath):
        raise HTTPException(404, f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    filename = os.path.basename(filepath)
    provider = _guess_provider(filepath)

    db = await get_db()
    try:
        if ext == ".xlsx" and provider == "eon":
            records = parse_eon_xlsx(filepath)
            consumption = extract_eon_consumption(records)

            imported_docs = 0
            imported_consumption = 0

            for rec in records:
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO documents 
                           (filename, filepath, provider, doc_type, doc_number, 
                            issue_date, due_date, amount_pln, payment_status, location)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (filename, filepath, rec["provider"], rec["doc_type"],
                         rec["doc_number"], rec["issue_date"], rec["due_date"],
                         rec["amount_pln"], rec["payment_status"], rec["location"]),
                    )
                    imported_docs += 1
                except Exception:
                    pass

            for cons in consumption:
                try:
                    await db.execute(
                        """INSERT OR IGNORE INTO consumption_records
                           (provider, utility_type, location, period_start, period_end,
                            cost_gross, is_estimate, extracted_by)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cons["provider"], cons["utility_type"], cons["location"],
                         cons["period_start"], cons["period_end"], cons["cost_gross"],
                         cons["is_estimate"], "parser"),
                    )
                    imported_consumption += 1
                except Exception:
                    pass

            await db.commit()
            return {
                "status": "ok",
                "provider": "eon",
                "documents": imported_docs,
                "consumption_records": imported_consumption,
                "records_preview": records[:5],
            }

        elif ext == ".pdf" and provider == "eon":
            parsed = parse_eon_pdf(filepath)

            # Store document
            await db.execute(
                """INSERT OR IGNORE INTO documents
                   (filename, filepath, provider, doc_type, doc_number,
                    issue_date, due_date, amount_pln, location, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, filepath, "eon", parsed["doc_type"],
                 parsed["doc_number"], parsed["issue_date"],
                 parsed.get("due_date"), parsed.get("amount_pln"),
                 parsed["location"], parsed["raw_text"][:5000]),
            )

            # Store consumption record
            period_start = parsed.get("period_start")
            period_end = parsed.get("period_end")

            doc_id = None
            cursor = await db.execute(
                "SELECT id FROM documents WHERE provider='eon' AND doc_number=?",
                (parsed["doc_number"],),
            )
            row = await cursor.fetchone()
            if row:
                doc_id = row[0]

            if period_start and period_end:
                await db.execute(
                    """INSERT OR IGNORE INTO consumption_records
                       (document_id, provider, utility_type, location,
                        period_start, period_end, consumption_kwh,
                        cost_net, cost_gross, tariff_group,
                        is_estimate, extracted_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (doc_id, "eon", "electricity", parsed["location"],
                     period_start, period_end,
                     parsed.get("consumption_kwh"),
                     parsed.get("cost_net"), parsed.get("cost_gross"),
                     parsed.get("tariff_group"),
                     parsed.get("is_estimate", 0), "parser"),
                )

                # Store cost components
                cons_cursor = await db.execute(
                    """SELECT id FROM consumption_records
                       WHERE provider='eon' AND period_start=? AND period_end=? AND location=?""",
                    (period_start, period_end, parsed["location"]),
                )
                cons_row = await cons_cursor.fetchone()
                if cons_row:
                    for comp in parsed.get("cost_components", []):
                        await db.execute(
                            """INSERT INTO cost_components
                               (consumption_record_id, component_name, quantity, unit,
                                unit_price, vat_rate, net_amount, gross_amount)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (cons_row[0], comp["name"],
                             comp.get("quantity"), comp.get("unit"),
                             comp.get("unit_price"), comp.get("vat_rate"),
                             comp.get("net_amount"), comp.get("gross_amount")),
                        )

            await db.commit()
            return {
                "status": "ok",
                "provider": "eon",
                "parsed": {k: v for k, v in parsed.items() if k != "raw_text"},
            }

        elif ext == ".pdf" and provider == "pgnig":
            parsed = parse_pgnig_pdf(filepath)

            # Store document
            await db.execute(
                """INSERT OR IGNORE INTO documents
                   (filename, filepath, provider, doc_type, doc_number,
                    issue_date, due_date, amount_pln, location, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, filepath, "pgnig", "faktura_rozliczeniowa",
                 parsed["doc_number"], parsed["issue_date"], parsed["due_date"],
                 parsed["amount_pln"], parsed["location"],
                 parsed["raw_text"][:5000]),
            )

            # Store consumption record
            period = parsed["period"]
            consumption = parsed["consumption"]
            totals = parsed["totals"]

            doc_id = None
            cursor = await db.execute(
                "SELECT id FROM documents WHERE provider='pgnig' AND doc_number=?",
                (parsed["doc_number"],),
            )
            row = await cursor.fetchone()
            if row:
                doc_id = row[0]

            if period["start"] and period["end"]:
                await db.execute(
                    """INSERT OR IGNORE INTO consumption_records
                       (document_id, provider, utility_type, location,
                        period_start, period_end, consumption_value, consumption_unit,
                        consumption_kwh, cost_net, cost_gross, meter_number,
                        meter_reading_start, meter_reading_end, is_estimate, extracted_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (doc_id, "pgnig", "gas", parsed["location"],
                     period["start"], period["end"],
                     consumption.get("m3"), "m3",
                     consumption.get("kwh"),
                     totals.get("net"), parsed["amount_pln"] or totals.get("gross"),
                     parsed["meter_number"],
                     consumption.get("meter_start"), consumption.get("meter_end"),
                     0, "parser"),
                )

                # Store cost components
                cons_cursor = await db.execute(
                    """SELECT id FROM consumption_records 
                       WHERE provider='pgnig' AND period_start=? AND period_end=?""",
                    (period["start"], period["end"]),
                )
                cons_row = await cons_cursor.fetchone()
                if cons_row:
                    for comp in parsed["cost_components"]:
                        await db.execute(
                            """INSERT INTO cost_components
                               (consumption_record_id, component_name, quantity, unit,
                                unit_price, vat_rate, net_amount)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (cons_row[0], comp["name"],
                             comp.get("quantity"), comp.get("unit"),
                             comp.get("unit_price"), comp.get("vat_rate"),
                             comp.get("net_amount")),
                        )

            await db.commit()

            # Optionally enhance with AI
            ai_result = None
            if use_ai:
                try:
                    ai_result = await extract_with_ai(parsed["raw_text"])
                except Exception as e:
                    ai_result = {"error": str(e)}

            return {
                "status": "ok",
                "provider": "pgnig",
                "parsed": {k: v for k, v in parsed.items() if k != "raw_text"},
                "ai_result": ai_result,
            }

        elif ext == ".pdf" and provider == "mpwik":
            parsed = parse_mpwik_pdf(filepath)

            if not parsed.get("readable", True):
                return {
                    "status": "skipped",
                    "provider": "mpwik",
                    "reason": "PDF text not readable (garbled)",
                }

            if not parsed["doc_number"]:
                return {
                    "status": "skipped",
                    "provider": "mpwik",
                    "reason": "Could not extract document number",
                }

            # Store document
            await db.execute(
                """INSERT OR IGNORE INTO documents
                   (filename, filepath, provider, doc_type, doc_number,
                    issue_date, due_date, amount_pln, location, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, filepath, "mpwik", parsed["doc_type"],
                 parsed["doc_number"], parsed["issue_date"], parsed["due_date"],
                 parsed["amount_pln"], parsed["location"],
                 parsed["raw_text"][:5000]),
            )

            # Store consumption record
            period = parsed["period"]
            consumption = parsed["consumption"]
            totals = parsed["totals"]

            doc_id = None
            cursor = await db.execute(
                "SELECT id FROM documents WHERE provider='mpwik' AND doc_number=?",
                (parsed["doc_number"],),
            )
            row = await cursor.fetchone()
            if row:
                doc_id = row[0]

            if period["start"] and period["end"] and not parsed["is_correction"]:
                await db.execute(
                    """INSERT OR IGNORE INTO consumption_records
                       (document_id, provider, utility_type, location,
                        period_start, period_end, consumption_value, consumption_unit,
                        cost_net, cost_gross, meter_number,
                        meter_reading_start, meter_reading_end, is_estimate, extracted_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (doc_id, "mpwik", "water", parsed["location"],
                     period["start"], period["end"],
                     consumption.get("consumption_m3"), "m3",
                     totals.get("net"), parsed["amount_pln"] or totals.get("gross"),
                     consumption.get("meter_number"),
                     consumption.get("meter_start"), consumption.get("meter_end"),
                     0, "parser"),
                )

                # Store cost components
                cons_cursor = await db.execute(
                    """SELECT id FROM consumption_records
                       WHERE provider='mpwik' AND period_start=? AND period_end=?""",
                    (period["start"], period["end"]),
                )
                cons_row = await cons_cursor.fetchone()
                if cons_row:
                    for comp in parsed["cost_components"]:
                        await db.execute(
                            """INSERT INTO cost_components
                               (consumption_record_id, component_name, quantity, unit,
                                unit_price, vat_rate, net_amount, gross_amount)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (cons_row[0], comp["name"],
                             comp.get("quantity"), comp.get("unit"),
                             comp.get("unit_price"), comp.get("vat_rate"),
                             comp.get("net_amount"), comp.get("gross_amount")),
                        )

            await db.commit()
            return {
                "status": "ok",
                "provider": "mpwik",
                "parsed": {k: v for k, v in parsed.items() if k != "raw_text"},
            }

        else:
            # Unknown format - try AI extraction
            if use_ai:
                import fitz
                text = ""
                if ext == ".pdf":
                    doc = fitz.open(filepath)
                    for page in doc:
                        text += page.get_text()
                    doc.close()
                else:
                    with open(filepath, "r", errors="ignore") as f:
                        text = f.read()

                ai_result = await extract_with_ai(text)
                return {"status": "ok", "provider": "unknown", "ai_result": ai_result}

            raise HTTPException(400, f"Cannot auto-parse {ext} from {provider}. Try with use_ai=true.")

    finally:
        await db.close()


@app.get("/api/documents")
async def list_documents(provider: Optional[str] = None):
    """List all imported documents."""
    db = await get_db()
    try:
        query = "SELECT * FROM documents"
        params = []
        if provider:
            query += " WHERE provider = ?"
            params.append(provider)
        query += " ORDER BY issue_date DESC"

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return {"documents": [dict(r) for r in rows]}
    finally:
        await db.close()


@app.get("/api/consumption")
async def get_consumption(
    provider: Optional[str] = None,
    utility_type: Optional[str] = None,
    location: Optional[str] = None,
    include_estimates: bool = True,
):
    """Get consumption records with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM consumption_records WHERE 1=1"
        params = []

        if provider:
            query += " AND provider = ?"
            params.append(provider)
        if utility_type:
            query += " AND utility_type = ?"
            params.append(utility_type)
        if location:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")
        if not include_estimates:
            query += " AND is_estimate = 0"

        query += " ORDER BY period_start DESC"

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return {"records": [dict(r) for r in rows]}
    finally:
        await db.close()


@app.get("/api/consumption/chart")
async def get_consumption_chart(
    utility_type: Optional[str] = None,
    location: Optional[str] = None,
):
    """Get consumption data formatted for charts."""
    db = await get_db()
    try:
        query = """
            SELECT provider, utility_type, location, period_start, period_end,
                   consumption_kwh, consumption_value, consumption_unit,
                   cost_net, cost_gross, is_estimate
            FROM consumption_records
            WHERE 1=1
        """
        params = []
        if utility_type:
            query += " AND utility_type = ?"
            params.append(utility_type)
        if location:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")

        query += " ORDER BY period_start ASC"

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        records = [dict(r) for r in rows]

        # Group by utility_type + location for chart series
        series = {}
        for rec in records:
            key = f"{rec['utility_type']}|{rec['location']}"
            if key not in series:
                series[key] = {
                    "utility_type": rec["utility_type"],
                    "location": rec["location"],
                    "provider": rec["provider"],
                    "data": [],
                }
            series[key]["data"].append({
                "period_start": rec["period_start"],
                "period_end": rec["period_end"],
                "consumption_kwh": rec["consumption_kwh"],
                "consumption_value": rec["consumption_value"],
                "consumption_unit": rec["consumption_unit"],
                "cost_gross": rec["cost_gross"],
                "cost_net": rec["cost_net"],
                "is_estimate": rec["is_estimate"],
            })

        return {"series": list(series.values())}
    finally:
        await db.close()


@app.get("/api/cost-components/{record_id}")
async def get_cost_components(record_id: int):
    """Get cost breakdown for a consumption record."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM cost_components WHERE consumption_record_id = ?",
            (record_id,),
        )
        rows = await cursor.fetchall()
        return {"components": [dict(r) for r in rows]}
    finally:
        await db.close()


@app.delete("/api/data/reset")
async def reset_data():
    """Reset all data (for development)."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM cost_components")
        await db.execute("DELETE FROM consumption_records")
        await db.execute("DELETE FROM documents")
        await db.commit()
        return {"status": "ok", "message": "All data cleared"}
    finally:
        await db.close()


# ── Static files (frontend) ────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ── Helpers ─────────────────────────────────────────────────


def _guess_provider(filepath: str) -> str:
    fp_lower = filepath.lower()
    if "eon" in fp_lower:
        return "eon"
    elif "pgnig" in fp_lower:
        return "pgnig"
    elif "mpwik" in fp_lower:
        return "mpwik"
    return "unknown"
