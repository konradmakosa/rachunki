#!/usr/bin/env python3
"""Batch process all invoices from Google Drive into the database."""

import asyncio
import os
import sys
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.database import init_db, get_db
from backend.parsers.eon_parser import parse_eon_xlsx, extract_eon_consumption
from backend.parsers.eon_pdf_parser import parse_eon_pdf
from backend.parsers.pgnig_parser import parse_pgnig_pdf
from backend.parsers.mpwik_parser import parse_mpwik_pdf

GDRIVE_DIR = os.path.expanduser(
    "~/Library/CloudStorage/GoogleDrive-konrad.makosa@gmail.com/My Drive/Płatnicza/rachunki"
)


def guess_provider(filepath):
    fp = filepath.lower()
    if "eon" in fp:
        return "eon"
    elif "pgnig" in fp:
        return "pgnig"
    elif "mpwik" in fp:
        return "mpwik"
    return "unknown"


async def main():
    await init_db()

    # Reset DB
    db = await get_db()
    await db.execute("DELETE FROM cost_components")
    await db.execute("DELETE FROM consumption_records")
    await db.execute("DELETE FROM documents")
    await db.commit()
    await db.close()
    print("🗑️  Baza wyczyszczona\n")

    stats = {"eon_xlsx": 0, "eon_pdf": 0, "pgnig": 0, "mpwik": 0, "skipped": 0, "errors": 0}

    # 1. Process e.on XLSX
    for fpath in glob.glob(os.path.join(GDRIVE_DIR, "eon", "*.xlsx")):
        print(f"📊 e.on XLSX: {os.path.basename(fpath)}")
        try:
            await process_eon_xlsx(fpath)
            stats["eon_xlsx"] += 1
        except Exception as e:
            print(f"   ❌ {e}")
            stats["errors"] += 1

    # 2. Process e.on PDFs
    for fpath in sorted(glob.glob(os.path.join(GDRIVE_DIR, "eon", "*.pdf"))):
        fname = os.path.basename(fpath)
        try:
            result = await process_eon_pdf(fpath)
            if result:
                stats["eon_pdf"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            print(f"   ❌ {fname}: {e}")
            stats["errors"] += 1

    # 3. Process PGNiG PDFs
    for fpath in sorted(glob.glob(os.path.join(GDRIVE_DIR, "pgnig", "*.pdf"))):
        fname = os.path.basename(fpath)
        try:
            result = await process_pgnig_pdf(fpath)
            if result:
                stats["pgnig"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            print(f"   ❌ {fname}: {e}")
            stats["errors"] += 1

    # 4. Process MPWiK PDFs
    for fpath in sorted(glob.glob(os.path.join(GDRIVE_DIR, "mpwik", "*.pdf"))):
        fname = os.path.basename(fpath)
        try:
            result = await process_mpwik_pdf(fpath)
            if result:
                stats["mpwik"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            print(f"   ❌ {fname}: {e}")
            stats["errors"] += 1

    # Summary
    print(f"\n{'='*50}")
    print(f"📊 Podsumowanie:")
    print(f"   e.on XLSX:  {stats['eon_xlsx']}")
    print(f"   e.on PDF:   {stats['eon_pdf']}")
    print(f"   PGNiG PDF:  {stats['pgnig']}")
    print(f"   MPWiK PDF:  {stats['mpwik']}")
    print(f"   Pominięte:  {stats['skipped']}")
    print(f"   Błędy:      {stats['errors']}")

    # Count DB records
    db = await get_db()
    cur = await db.execute("SELECT COUNT(*) FROM documents")
    docs = (await cur.fetchone())[0]
    cur = await db.execute("SELECT COUNT(*) FROM consumption_records")
    cons = (await cur.fetchone())[0]
    cur = await db.execute("SELECT COUNT(*) FROM cost_components")
    comps = (await cur.fetchone())[0]
    await db.close()
    print(f"\n   📄 Dokumenty w bazie:  {docs}")
    print(f"   📈 Rekordy zużycia:   {cons}")
    print(f"   💰 Składniki kosztów: {comps}")


async def process_eon_xlsx(fpath):
    db = await get_db()
    try:
        records = parse_eon_xlsx(fpath)
        consumption = extract_eon_consumption(records)
        fname = os.path.basename(fpath)

        for rec in records:
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO documents
                       (filename, filepath, provider, doc_type, doc_number,
                        issue_date, due_date, amount_pln, payment_status, location)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fname, fpath, rec["provider"], rec["doc_type"],
                     rec["doc_number"], rec["issue_date"], rec["due_date"],
                     rec["amount_pln"], rec["payment_status"], rec["location"]),
                )
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
            except Exception:
                pass

        await db.commit()
        print(f"   ✅ {len(records)} dokumentów, {len(consumption)} rekordów zużycia")
    finally:
        await db.close()


async def process_eon_pdf(fpath):
    fname = os.path.basename(fpath)
    parsed = parse_eon_pdf(fpath)

    if not parsed.get("doc_number"):
        return False

    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO documents
               (filename, filepath, provider, doc_type, doc_number,
                issue_date, due_date, amount_pln, location, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fname, fpath, "eon", parsed["doc_type"],
             parsed["doc_number"], parsed["issue_date"],
             parsed.get("due_date"), parsed.get("amount_pln"),
             parsed["location"], parsed["raw_text"][:5000]),
        )

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
        return True
    finally:
        await db.close()


async def process_pgnig_pdf(fpath):
    fname = os.path.basename(fpath)
    parsed = parse_pgnig_pdf(fpath)

    if not parsed.get("doc_number"):
        return False

    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO documents
               (filename, filepath, provider, doc_type, doc_number,
                issue_date, due_date, amount_pln, location, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fname, fpath, "pgnig", "faktura_rozliczeniowa",
             parsed["doc_number"], parsed["issue_date"], parsed["due_date"],
             parsed["amount_pln"], parsed["location"],
             parsed["raw_text"][:5000]),
        )

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
        return True
    finally:
        await db.close()


async def process_mpwik_pdf(fpath):
    fname = os.path.basename(fpath)
    parsed = parse_mpwik_pdf(fpath)

    if not parsed.get("readable", True) or not parsed.get("doc_number"):
        return False

    db = await get_db()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO documents
               (filename, filepath, provider, doc_type, doc_number,
                issue_date, due_date, amount_pln, location, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fname, fpath, "mpwik", parsed["doc_type"],
             parsed["doc_number"], parsed["issue_date"], parsed["due_date"],
             parsed["amount_pln"], parsed["location"],
             parsed["raw_text"][:5000]),
        )

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
        return True
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
