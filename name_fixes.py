import sqlite3
from pathlib import Path

DB_PATH = Path("rules.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS name_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original TEXT UNIQUE NOT NULL,
            corrected TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def get_fixes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT original, corrected FROM name_fixes")
    rows = c.fetchall()
    conn.close()
    return rows

def save_single_fix(original, corrected):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT corrected FROM name_fixes WHERE original=?", (original,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE name_fixes SET corrected=? WHERE original=?", (corrected, original))
    else:
        c.execute("INSERT INTO name_fixes (original, corrected) VALUES (?, ?)", (original, corrected))
    conn.commit()
    conn.close()
