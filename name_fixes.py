import sqlite3
from pathlib import Path

DB_PATH = Path("rules.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS name_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original TEXT NOT NULL,
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

def save_fixes(df):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM name_fixes")
    for _, row in df.iterrows():
        c.execute("INSERT INTO name_fixes (original, corrected) VALUES (?, ?)",
                  (row["original"], row["corrected"]))
    conn.commit()
    conn.close()
