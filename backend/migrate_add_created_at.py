import sqlite3
import os

def migrate():
    db_path = os.getenv('DATABASE_URL', 'sqlite:///./test.db')
    if db_path.startswith('sqlite:///'):
        db_path = db_path.replace('sqlite:///', '')
    print(f"Migrating database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # Check if created_at already exists
    cursor.execute("PRAGMA table_info(rfps)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'created_at' in columns:
        print('Column created_at already exists.')
        return
    cursor.execute("ALTER TABLE rfps ADD COLUMN created_at DATETIME DEFAULT (datetime('now'))")
    conn.commit()
    print('Migration completed: created_at column added.')
    conn.close()

if __name__ == '__main__':
    migrate()
