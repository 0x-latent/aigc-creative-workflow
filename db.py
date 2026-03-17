import sqlite3
import os

DB_PATH = os.path.join("output", "campaign_tracker.db")


def init_db():
    os.makedirs("output", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaign_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            step TEXT NOT NULL,
            input_snapshot TEXT,
            output_snapshot TEXT,
            prompt_template TEXT,
            model TEXT,
            input_hash TEXT,
            review_status TEXT,
            review_feedback TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    return DB_PATH


def get_connection():
    return sqlite3.connect(DB_PATH)
