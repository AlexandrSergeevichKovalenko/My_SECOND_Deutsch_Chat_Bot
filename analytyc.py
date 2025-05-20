import os
import logging
import psycopg2
import pandas as pd
import asyncio

# === Подключение к базе данных PostgreSQL ===
DATABASE_URL = os.getenv("DATABASE_URL_RAILWAY")

if DATABASE_URL:
    logging.info("✅ DATABASE_URL успешно загружен!")
else:   
    logging.error("❌ Ошибка: DATABASE_URL не задан. Проверь переменные окружения!")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Проверка подключения
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT version();")
db_version = cursor.fetchone()

print(f"✅ База данных подключена! Версия: {db_version}")

cursor.close()
conn.close()

async def load_data_for_analytics(user_id: int, period: str = 'week') -> pd.DataFrame:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT session_id, username, start_time, end_time FROM user_progress_deepseek
                WHERE user_id = %s;
            """, (user_id, ))
            
            result_from_user_progress_deepseek = cursor.fetchall()

            columns_user_progress_deepseek = [desc[0] for desc in cursor.description]
            df_progress = pd.DataFrame(result_from_user_progress_deepseek, columns=columns_user_progress_deepseek)

            cursor.execute("""
                SELECT session_id, username, sentence_id, score, timestamp FROM translations_deepseek
                WHERE user_id = %s;
            """, (user_id, ))
            result_translations_deepseek = cursor.fetchall()          
            columns_translations_deepseek = [desc[0] for desc in cursor.description]
            df_translations = pd.DataFrame(result_translations_deepseek, columns=columns_translations_deepseek)

            cursor.execute("""
                SELECT sentence_id, score, attempt, date FROM successful_translations
                WHERE user_id = %s;
            """, (user_id, ))
            result_success_translations = cursor.fetchall()          
            columns_success = [desc[0] for desc in cursor.description]
            df_success = pd.DataFrame(result_success_translations, columns=columns_success)

            cursor.execute("""
                SELECT added_data, main_category, sub_category, mistake_count, first_seen, last_seen, sentence_id, score, attempt FROM detailed_mistakes_deepseek
                WHERE user_id = %s;
            """, (user_id, ))
            
            result_mistakes = cursor.fetchall()          
            columns_mistakes = [desc[0] for desc in cursor.description]
            df_mistakes = pd.DataFrame(result_mistakes, columns=columns_mistakes)

            cursor.execute("""
                SELECT date, unique_id, session_id, id_for_mistake_table FROM daily_sentences_deepseek
                WHERE user_id = %s;
            """, (user_id, ))

            result_sentences = cursor.fetchall()
            column_sentences = [desc[0] for desc in cursor.description]
            df_sentences = pd.DataFrame(result_sentences, columns=column_sentences)

            # Чтобы не Ловить ошибки в groupby, to_period() и других операциях:
            df_progress['start_time'] = pd.to_datetime(df_progress['start_time'])
            df_progress['end_time'] = pd.to_datetime(df_progress['end_time'])

            df_translations['timestamp'] = pd.to_datetime(df_translations['timestamp'])
            df_success['date'] = pd.to_datetime(df_success['date'])
            df_mistakes['added_data'] = pd.to_datetime(df_mistakes['added_data'])
            df_mistakes['first_seen'] = pd.to_datetime(df_mistakes['first_seen'])
            df_mistakes['last_seen'] = pd.to_datetime(df_mistakes['last_seen'])
            df_sentences['date'] = pd.to_datetime(df_sentences['date'])


    return {
        "progress": df_progress,
        "translations": df_translations,
        "success": df_success,
        "mistakes": df_mistakes,
        "sentences": df_sentences
    }


if __name__ == "__main__":
    dfs = asyncio.run(load_data_for_analytics(117649764))
    dfs["translations"].head()
    #print(dfs)

