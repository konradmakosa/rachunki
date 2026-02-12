import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rachunki.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    provider TEXT NOT NULL,          -- 'eon' or 'pgnig'
    doc_type TEXT NOT NULL,          -- 'faktura_rozliczeniowa', 'prognoza', 'nota_odsetkowa', 'wplata'
    doc_number TEXT,
    issue_date TEXT,
    due_date TEXT,
    amount_pln REAL,
    payment_status TEXT,
    location TEXT,                   -- e.g. 'Płatnicza 65', 'Rydygiera 6'
    raw_text TEXT,
    imported_at TEXT DEFAULT (datetime('now')),
    UNIQUE(provider, doc_number)
);

CREATE TABLE IF NOT EXISTS consumption_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES documents(id),
    provider TEXT NOT NULL,
    utility_type TEXT NOT NULL,      -- 'electricity', 'gas'
    location TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    consumption_value REAL,
    consumption_unit TEXT,           -- 'kWh', 'm3'
    consumption_kwh REAL,            -- normalized to kWh
    cost_net REAL,
    cost_gross REAL,
    cost_currency TEXT DEFAULT 'PLN',
    tariff_group TEXT,
    meter_number TEXT,
    meter_reading_start REAL,
    meter_reading_end REAL,
    is_estimate INTEGER DEFAULT 0,   -- 0=actual, 1=estimate/prognoza
    extracted_by TEXT,               -- 'parser' or 'ai'
    extracted_at TEXT DEFAULT (datetime('now')),
    UNIQUE(provider, location, period_start, period_end, utility_type)
);

CREATE TABLE IF NOT EXISTS cost_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumption_record_id INTEGER REFERENCES consumption_records(id),
    component_name TEXT NOT NULL,    -- e.g. 'Paliwo gazowe', 'Dystrybucyjna stała', 'Opłata abonamentowa'
    quantity REAL,
    unit TEXT,
    unit_price REAL,
    vat_rate REAL,
    net_amount REAL,
    gross_amount REAL
);
"""


async def get_db() -> aiosqlite.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        await db.close()
