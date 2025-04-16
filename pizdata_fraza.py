from deepseek_bot_copy import get_db_connection
import os
from anthropic import AsyncAnthropic

DATABASE_URL = os.getenv("DATABASE_URL_RAILWAY")
CLAUDE_API_KEY = os.get("CLAUDE_API_KEY")

async def pizdata():
    with get_db_connection() as connection:
        with connection.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pizdata (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES translations_deepseek(user_id),
                username TEXT,
                germ_pizdata_fraze TEXT,
                russion_pizdata_translation TEXT,
                example_pizdata TEXT,
                date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_sent TIMESTAMP,
                category TEXT CHECK (category IN ('Work', 'Hobby', 'Friends', 'Affront')),
                count_sent INT DEFAULT 0,
                CONSTRAINT for_pizdata_table UNIQUE (id, user_id, germ_pizdata_fraze)
                );
            """)
    
    client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

    
