import aiosqlite

DB = "messages.db"

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_connection_id TEXT,
            message_id INTEGER,
            chat_id INTEGER,
            user_id INTEGER,
            text TEXT
        )
        """)
        await db.commit()