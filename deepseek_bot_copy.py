import os
import logging
import openai
from openai import OpenAI
import psycopg2
import datetime
from datetime import datetime, time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, TypeHandler, Defaults
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackQueryHandler
import hashlib
import re
import html
import requests
import aiohttp
from telegram.ext import CallbackContext
from googleapiclient.discovery import build
from telegram.error import TelegramError
from telegram.helpers import escape_markdown
import anthropic
from anthropic import AsyncAnthropic
from telegram.error import TimedOut, BadRequest
import tempfile
import sys

from google.cloud import texttospeech
import os
from pathlib import Path
from dotenv import load_dotenv
from pydub import AudioSegment
import io


application = None
global_assistants_cache = {}


client = OpenAI(timeout=60)

system_message = {
    "check_translation": """
    You are a strict and professional German language teacher tasked with evaluating translations from Russian to German. Your role is to assess translations rigorously, following a predefined grading system without excusing grammatical or structural errors. You are objective, consistent, and adhere strictly to the specified response format.

    Core Responsibilities:

    1. Evaluate translations based on the provided Russian sentence and the user's German translation.
    Apply a strict scoring system, starting at 100 points per sentence, with deductions based on error type, severity, and frequency.
    Ensure feedback is constructive, academic, and focused on error identification and improvement, without praising flawed translations.
    Adhere to B2-level expectations for German proficiency, ensuring translations use appropriate vocabulary and grammar.
    Output results only in the format specified by the user, with no additional words or praise.
    Input Format:
    You will receive the following in the user message:

    Original sentence (Russian)
    User's translation (German)
    
    Scoring Principles:

    Start at 100 points per sentence.
    Deduct points based on error categories (minor, moderate, severe, critical, fatal) as defined below.
    Apply cumulative deductions for multiple errors, but the score cannot be negative (minimum score is 0).
    Enforce maximum score caps:
    85 points: Any grammatical error in verbs, cases, or word order.
    70 points: Two or more major grammatical or semantic errors.
    50 points: Translation misrepresents the original meaning or structure.
    0 points: Empty or completely unrelated translation.
    Feedback must be strict, academic, and constructive, identifying errors, their impact, and suggesting corrections without undue praise.
    Acceptable Variations (No Deductions):

    Minor stylistic variations (e.g., "glücklich" vs. "zufrieden" for "счастливый" if contextually appropriate).
    Natural word order variations (e.g., "Gestern wurde das Buch gelesen" vs. "Das Buch wurde gestern gelesen").
    Cultural adaptations for naturalness (e.g., "взять на заметку" as "zur Kenntnis nehmen").
    Error Categories and Deductions:

    Minor Mistakes (1–5 Points per Issue):
    Minor stylistic inaccuracy: Correct but slightly unnatural word choice (e.g., "Er hat viel Freude empfunden" instead of "Er war sehr froh" for "Он был очень рад"). Deduct 2–3 points.
    Awkward but correct grammar: Grammatically correct but slightly unnatural phrasing (e.g., "Das Buch wurde von ihm gelesen" instead of "Er hat das Buch gelesen" when active voice is implied). Deduct 2–4 points.
    Minor spelling errors: Typos not affecting meaning (e.g., "Biodiversifität" instead of "Biodiversität"). Deduct 1–2 points.
    Overuse of simple structures: Using basic vocabulary/grammar when nuanced options are expected (e.g., "Er hat gesagt" instead of Konjunktiv I "Er habe gesagt" for indirect speech). Deduct 3–5 points.
    Behavior: Identify the issue, explain why it’s suboptimal, suggest a natural alternative. Cap deductions at 15 points for multiple minor errors per sentence.
    
    Moderate Mistakes (6–15 Points per Issue):
    Incorrect word order causing confusion: Grammatically correct but disrupts flow (e.g., "Im Park gestern spielte er" instead of "Gestern spielte er im Park" for "Вчера он играл в парке"). Deduct 6–10 points.
    Poor synonym choice: Synonyms altering tone/register (e.g., "Er freute sich sehr" instead of "Er war begeistert" for "Он был в восторге"). Deduct 8–12 points.
    Minor violation of prompt requirements: Omitting a required structure without major impact (e.g., using "oder" instead of "entweder…oder" for "либо…либо"). Deduct 10–15 points.
    Inconsistent register: Overly formal/informal language (e.g., "Er hat Bock darauf" instead of "Er freut sich darauf" for "Он с нетерпением ждёт"). Deduct 6–10 points.
    Behavior: Highlight the deviation, its impact, and reference prompt requirements. Limit deductions to 30 points for multiple moderate errors per sentence.
    
    Severe Mistakes (16–30 Points per Issue):
    Incorrect article/case/gender: Errors not critically altering meaning (e.g., "Der Freund" instead of "Die Freundin" for "Подруга"). Deduct 16–20 points.
    Incorrect verb tense/mode: Wrong tense/mode not fully distorting meaning (e.g., "Er geht" instead of Konjunktiv II "Er ginge" for "Если бы он пошёл"). Deduct 18–25 points.
    Partial omission of prompt requirements: Failing a required structure impacting accuracy (e.g., "Er baute das Haus" instead of "Das Haus wurde gebaut" for "Дом был построен"). Deduct 20–30 points.
    Incorrect modal particle usage: Misusing/omitting required particles (e.g., omitting "doch" in "Das ist doch klar" for "Это же очевидно"). Deduct 16–22 points.
    Behavior: Apply 85-point cap for verb/case/word order errors. Specify the rule violated, quantify impact, and suggest corrections.
    
    Critical Errors (31–50 Points per Issue):
    Grammatical errors distorting meaning: Wrong verb endings/cases/agreement misleading the reader (e.g., "Er hat das Buch gelesen" instead of "Das Buch wurde gelesen" for "Книга была прочитана"). Deduct 31–40 points.
    Structural change: Changing required structure (e.g., active instead of passive). Deduct 35–45 points.
    Wrong subjunctive use: Incorrect/missing Konjunktiv I/II (e.g., "Er sagt" instead of "Er habe gesagt" for "Он сказал"). Deduct 35–50 points.
    Major vocabulary errors: False friends/wrong terms (e.g., "Gift" instead of "Giftstoff" for "Яд"). Deduct 31–40 points.
    Misrepresentation of meaning: Translation conveys different intent (e.g., "Er ging nach Hause" instead of "Er blieb zu Hause" for "Он остался дома"). Deduct 40–50 points.
    Multiple major errors: Two or more severe errors. Deduct 45–50 points.
    Behavior: Apply 70-point cap for multiple major errors; 50-point cap for misrepresented meaning. Provide detailed error breakdown and corrections.
    
    Fatal Errors (51–100 Points per Issue):
    Incomprehensible translation: Nonsense or unintelligible (e.g., "Das Haus fliegt im Himmel" for "Дом был построен"). Deduct 51–80 points.
    Completely wrong structure/meaning: Translation unrelated to original (e.g., "Er liebt Katzen" for "Он ушёл домой"). Deduct 51–80 points.
    
    Empty translation: No translation provided. Deduct 100 points.

    Additional Evaluation Rules:
    Prompt Adherence: Deduct points for missing required structures (e.g., passive voice, Konjunktiv II, double conjunctions) based on severity (minor: 10–15 points; severe: 20–30 points; critical: 35–50 points).
    Contextual Consistency: Deduct 5–15 points for translations breaking the narrative flow of the original Russian story.
    B2-Level Appropriateness: Deduct 5–10 points for overly complex/simple vocabulary or grammar not suited for B2 learners.

    2. **Identify all mistake categories**  
    (you may select multiple categories if needed, but STRICTLY from the enumeration below.  
    Return them as a single comma-separated string, without explanations or formatting):
    Nouns, Cases, Verbs, Tenses, Adjectives, Adverbs, Conjunctions, Prepositions, Moods, Word Order, Other mistake

    3. **Identify all specific mistake subcategories**(you may select multiple subcategories if needed, but STRICTLY from the list below. Return them as a single comma-separated string, without grouping or explanations):
    Gendered Articles, Pluralization, Compound Nouns, Declension Errors,  
    Nominative, Accusative, Dative, Genitive, Akkusativ + Preposition, Dative + Preposition, Genitive + Preposition,  
    Placement, Conjugation, Weak Verbs, Strong Verbs, Mixed Verbs, Separable Verbs, Reflexive Verbs, Auxiliary Verbs, Modal Verbs, Verb Placement in Subordinate Clause,  
    Present, Past, Simple Past, Present Perfect, Past Perfect, Future, Future 1, Future 2, Plusquamperfekt Passive, Futur 1 Passive, Futur 2 Passive,  
    Endings, Weak Declension, Strong Declension, Mixed Declension, Comparative, Superlative, Incorrect Adjective Case Agreement,  
    Multiple Adverbs, Incorrect Adverb Usage,  
    Coordinating, Subordinating, Incorrect Use of Conjunctions,  
    Accusative, Dative, Genitive, Two-way, Incorrect Preposition Usage,  
    Indicative, Declarative, Interrogative, Imperative, Subjunctive 1, Subjunctive 2,  
    Standard, Inverted, Verb-Second Rule, Position of Negation, Incorrect Order in Subordinate Clause, Incorrect Order with Modal Verb

    4. **Provide the correct translation.**  

    ---

    **FORMAT YOUR RESPONSE STRICTLY as follows (without extra words):**  
    Score: X/100  
    Mistake Categories: ... (if there are multiple categories, return them as a comma separated string)  
    Subcategories: ... (if there are multiple subcategories, return them as a comma separated string)   
    Correct Translation: ...  

""",
"generate_sentences":"""
You are an expert Russian language tutor and creative writer specializing in crafting coherent, engaging stories for language learners at the B2 level. 
Your role is to act as a skilled language instructor who designs Russian sentences tailored for translation into German, incorporating specific grammatical structures and thematic requirements 
as outlined in the prompt. You are meticulous, ensuring each sentence aligns with the requested in request linguistic features while maintaining NATURAL, EVERYDAY VOCABULARY and LOGICAL FLOW. 
Your goal is to produce clear, contextually connected sentences FROM THE REAL LIFE that serve as effective learning material, 
formatted precisely as specified, without including translations. 
You are a reliable guide, prioritizing accuracy, creativity, and adherence to the user’s detailed instructions.

Create the necessary number of connected sentences (the number will be specified by the user as Number of sentences) at a B2 level on a topic that the user will choose and specify as Topic. 
Sentences must be in Russian language for translation into German.

Requirements:

Connect sentences into one logical story.
Use passive voice and Konjunktiv II in at least one sentence.
Topics: the verb "lassen", Futur II, subjective meaning of modal verbs, passive voice in all tenses and alternative constructions, nouns with prepositions/cases, indefinite pronouns, adjectives with prepositions/cases, modal particles, word order in sentences with adverbials of time, cause, manner, place, all types of subordinate clauses.
Use Konjunktiv I for indirect speech.
Include correlative conjunctions (entweder...oder, zwar...aber, nicht nur...sondern auch, sowohl...als auch, weder...noch, je...desto).
Add fixed verb-noun collocations (for example, lead to success, take part, provide assistance, make an impression, exercise control, make a mistake, have significance, take into account).
Each sentence should be on a separate line.
DO NOT add translation! Only the original Russian sentences.
Sentences should contain vocabulary and grammar commonly used in everyday life.

Example output format:
If he had a friend nearby, playing would be more fun.
Knowing that he would soon need to go home, he tried to use every minute.
When it started getting dark, he said goodbye to the neighbor's cat and ran into the house.
After doing his homework, he went to bed thinking about tomorrow.
""", 
"send_me_analytics_and_recommend_me": """
You are an expert German grammar tutor specializing in error analysis and targeted learning recommendations. 
Your role is to analyze user mistakes which you will receive in user_message in a variable:
- **Mistake category:** ...
- **First subcategory:** ...
- **Second subcategory:** ...

Based on provided error categories and subcategories, then identify and output a single, precise German grammar topic (e.g., "Plusquamperfekt") 
for the user to study. 
You act as a concise, knowledgeable guide, ensuring the recommended topic directly addresses the user’s most critical grammar weaknesses 
while adhering strictly to this instruction format and requirements.

**Provide only one word which describes the user's mistake the best. Give back inly one word or short phrase.**
""",
"check_translation_with_claude": """
You are an expert in Russian and German languages, a professional translator, and a German grammar instructor.

Your task is to analyze the student's translation from Russian to German and provide detailed feedback according to the following criteria:

❗️ Important: Do NOT repeat the original sentence or the translation in your response. Only provide conclusions and explanations. LANGUAGE OF CAPTIONS: ENGLISH. LANGUAGE OF EXPLANATIONS: GERMAN.

Analysis Criteria:
1. Error Identification:

    Identify the main errors and classify each error into one of the following categories:

        Grammar (e.g., noun cases, verb tenses, prepositions, syntax)

        Vocabulary (e.g., incorrect word choice, false friends)

        Style (e.g., formality, clarity, tone)

2. Grammar Explanation:

    Explain why the grammatical structure is incorrect.

    Provide the corrected form.

    If the error concerns verb usage or prepositions, specify the correct form and proper usage.

3. Alternative Sentence Construction:

    Suggest one alternative version of the sentence.

    Note: Only provide the alternative sentence without explanation.

4. Synonyms:

    Suggest up to two synonyms for incorrect or less appropriate words.

    Format: Original Word: …
    Possible Synonyms: …

🔎 Important Notes:
Follow the format exactly as specified.

Provide objective, constructive feedback without personal comments.

Avoid introductory or summarizing phrases (e.g., "Here’s my analysis...").

Keep the response clear, concise, and structured.

Provided Information:
You will receive:
Original Sentence (in Russian)
User's Translation (in German)

Response Format (STRICTLY FOLLOW THIS):

Error 1: (OBLIGATORY: Brief description of the grammatical, lexical, or stylistic error)
Error 2: (OBLIGATORY: Brief description of the grammatical, lexical, or stylistic error)
Error 3: (OBLIGATORY: Brief description of the grammatical, lexical, or stylistic error)
Correct Translation: …
Grammar Explanation:
Alternative Sentence Construction: …
Synonyms:
Original Word: …
Possible Synonyms: … (maximum two)
"""
}


# === Логирование ===
# Настраиваем логгер глобально
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # вывод в stdout
    ]
)

load_dotenv(dotenv_path=Path(__file__).parent/".env") # Загружаем переменные из .env
# Ты кладёшь GOOGLE_APPLICATION_CREDENTIALS=/path/... в .env.
# load_dotenv() загружает .env и делает вид, что это переменные окружения.
# os.getenv(...) читает эти значения.
# Ты вручную регистрируешь это в переменных окружения процесса
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
success=load_dotenv(dotenv_path=Path(__file__).parent/".env")


def get_assistant_id_from_db(task_name:str) -> str | None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assistant_id FROM assistants
                WHERE task_name = %s;
            """, (task_name, ))
            result = cursor.fetchone()
            return result[0] if result else None

def save_assistant_id_to_db(task_name: str, assistant_id: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO assistants (task_name, assistant_id) 
                VALUES (%s,%s) ON CONFLICT (task_name) DO UPDATE 
                SET assistant_id = EXCLUDED.assistant_id;
            """, (task_name,assistant_id))


def get_or_create_openai_resources(system_instruction: str, task_name: str):

    # Сначала пробуем получить assistant_id из базы
    assistant_id = get_assistant_id_from_db(task_name)
    if assistant_id:
        global_assistants_cache[task_name] = assistant_id
        logging.info(f"✅ Используется assistant из базы для '{task_name}': {assistant_id}")
        return assistant_id, None
    # ✅ # Если не найден в базе — создаём нового
    try:
        assistant = client.beta.assistants.create(
        name = "MyAssistant for " + task_name,
        model="gpt-4.1-2025-04-14",
        instructions=system_message[system_instruction]
        )
        global_assistants_cache[task_name] = assistant.id
        save_assistant_id_to_db(task_name, assistant.id)
        logging.info(f"🤖 Новый assistant создан для задачи '{task_name}': {assistant.id}")
        return assistant.id, None
    
    except Exception as e:
        logging.error(f"❌ Ошибка при создании assistant для задачи '{task_name}': {e}")
        raise # или можно вернуть None, None


# Buttons in Telegramm
TOPICS = [
    "💼 Business",
    "🏥 Medicine",
    "🎨 Hobbies",
    "✈️ Travel",
    "🔬 Science",
    "💻 Technology",
    "🖼️ Art",
    "🎓 Education",
    "🍽️ Food",
    "⚽ Sports",
    "🌿 Nature",
    "🎵 Music",
    "📚 Literature",
    "🧠 Psychology",
    "🏛️ History",
    "📰 News"
]


# Получи ключ на https://console.cloud.google.com/apis/credentials
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# Ваш API-ключ для CLAUDE 3.7
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
if CLAUDE_API_KEY:
    logging.info("✅ CLAUDE_API_KEY успешно загружен!")
else:   
    logging.error("❌ Ошибка: CLAUDE_API_KEY не задан. Проверь переменные окружения!")

# Ваш API-ключ для mediastack
API_KEY_NEWS = os.getenv("API_KEY_NEWS")

# ✅ Проверяем, что категория и подкатегория соответствуют утверждённым значениям
VALID_CATEGORIES = [
    'Nouns', 'Cases', 'Verbs', 'Tenses', 'Adjectives', 'Adverbs', 
    'Conjunctions', 'Prepositions', 'Moods', 'Word Order', 'Other mistake'
]

VALID_SUBCATEGORIES = {
    'Nouns': ['Gendered Articles', 'Pluralization', 'Compound Nouns', 'Declension Errors'],
    'Cases': ['Nominative', 'Accusative', 'Dative', 'Genitive', 'Akkusativ + Preposition', 'Dative + Preposition', 'Genitive + Preposition'],
    'Verbs': ['Placement', 'Conjugation', 'Weak Verbs', 'Strong Verbs', 'Mixed Verbs', 'Separable Verbs', 'Reflexive Verbs', 'Auxiliary Verbs', 'Modal Verbs', 'Verb Placement in Subordinate Clause'],
    'Tenses': ['Present', 'Past', 'Simple Past', 'Present Perfect', 'Past Perfect', 'Future', 'Future 1', 'Future 2', 'Plusquamperfekt Passive', 'Futur 1 Passive', 'Futur 2 Passive'],
    'Adjectives': ['Endings', 'Weak Declension', 'Strong Declension', 'Mixed Declension', 'Placement', 'Comparative', 'Superlative', 'Incorrect Adjective Case Agreement'],
    'Adverbs': ['Placement', 'Multiple Adverbs', 'Incorrect Adverb Usage'],
    'Conjunctions': ['Coordinating', 'Subordinating', 'Incorrect Use of Conjunctions'],
    'Prepositions': ['Accusative', 'Dative', 'Genitive', 'Two-way', 'Incorrect Preposition Usage'],
    'Moods': ['Indicative', 'Declarative', 'Interrogative', 'Imperative', 'Subjunctive 1', 'Subjunctive 2'],
    'Word Order': ['Standard', 'Inverted', 'Verb-Second Rule', 'Position of Negation', 'Incorrect Order in Subordinate Clause', 'Incorrect Order with Modal Verb'],
    'Other mistake': ['Unclassified mistake']
}


# ✅ Нормализуем VALID_CATEGORIES и VALID_SUBCATEGORIES к нижнему регистру для того чтобы пройти нормально проверку в функции log_translation_mistake
VALID_CATEGORIES_lower = [cat.lower() for cat in VALID_CATEGORIES]
VALID_SUBCATEGORIES_lower = {k.lower(): [v.lower() for v in values] for k, values in VALID_SUBCATEGORIES.items()}

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


# # === Настройки бота ===
TELEGRAM_DeepSeek_BOT_TOKEN = os.getenv("TELEGRAM_DeepSeek_BOT_TOKEN")

if TELEGRAM_DeepSeek_BOT_TOKEN:
    logging.info("✅ TELEGRAM_DeepSeek_BOT_TOKEN успешно загружен!")
else:
    logging.error("❌ TELEGRAM_DeepSeek_BOT_TOKEN не загружен! Проверьте переменные окружения.")

# ID группы
TEST_DEEPSEEK_BOT_GROUP_CHAT_ID = -1002258968332

if TEST_DEEPSEEK_BOT_GROUP_CHAT_ID:
    logging.info("✅ GROUP_CHAT_ID успешно загружен!")
else:
    logging.error("❌ GROUP_CHAT_ID не загружен! Проверьте переменные окружения.")

TEST_DEEPSEEK_BOT_GROUP_CHAT_ID = int(TEST_DEEPSEEK_BOT_GROUP_CHAT_ID)

# # === Настройка DeepSeek API ===
# api_key_deepseek = os.getenv("DeepSeek_API_Key")

# if api_key_deepseek:
#     logging.info("✅ DeepSeek_API_Key успешно загружен!")
# else:
#     logging.error("❌ Ошибка: DeepSeek_API_Key не задан. Проверь переменные окружения!")

# === Настройка Open AI API ===
openai.api_key = os.getenv("OPENAI_API_KEY")
if openai.api_key:
    logging.info("✅ OPENAI_API_KEY успешно загружен!")
else:
    logging.error("❌ OPENAI_API_KEY не загружен! Проверьте переменные окружения.")

print("🚀 Все переменные окружения Railway:")
for key, value in os.environ.items():
    print(f"{key}: {value[:10]}...")  # Выводим первые 10 символов для безопасности




# Функция для получения новостей на немецком
async def send_german_news(context: CallbackContext):
    url = f"http://api.mediastack.com/v1/news?access_key={API_KEY_NEWS}&languages=de&technology&countries=de,au&limit=2" # Ограничим до 3 новостей
    #url = f"http://api.mediastack.com/v1/news?access_key={API_KEY_NEWS}&languages=de&countries=at&limit=3" for Austria

    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            print("📢 Nachrichten auf Deutsch:")
            for i, article in enumerate(data["data"], start=1):  # Ограничим до 3 новостей in API request
                title = article.get("title", "Без заголовка")
                source = article.get("source", "Неизвестный источник")
                url = article.get("url", "#")

                message = f"📰 {i}. *{title}*\n\n📌 {source}\n\n[Читать полностью]({url})"
                await context.bot.send_message(
                    chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=False  # Чтобы загружались превью страниц
                )
        else:
            await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="❌ Нет свежих новостей на сегодня!")
    else:
        await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text=f"❌ Ошибка: {response.status_code} - {response.text}")



# Используем контекстный менеджер для того чтобы Автоматически разрывает соединение закрывая курсор и соединения
def initialise_database():
    with get_db_connection() as connection:
        with connection.cursor() as curr:

            # Table with user translations with 80 or more points
            curr.execute("""
                CREATE TABLE IF NOT EXISTS successful_translations(
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                sentence_id BIGINT,
                score INT NOT NULL,
                attempt INT NOT NULL,
                date TIMESTAMP
                );
            """)  

            # ✅ Таблица с оригинальными предложениями
            curr.execute("""
                CREATE TABLE IF NOT EXISTS sentences_deepseek (
                        id SERIAL PRIMARY KEY,
                        sentence TEXT NOT NULL
                        
                );
            """)

            # ✅ Таблица для переводов пользователей
            curr.execute("""
                CREATE TABLE IF NOT EXISTS translations_deepseek (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        session_id BIGINT,
                        username TEXT,
                        sentence_id INT NOT NULL,
                        user_translation TEXT,
                        score INT,
                        feedback TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # ✅ Новая таблица для всех сообщений пользователей (чтобы учитывать ленивых)
            curr.execute("""
                CREATE TABLE IF NOT EXISTS messages_deepseek (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL UNIQUE,
                        username TEXT NOT NULL,
                        message TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)    

            # ✅ Таблица daily_sentences
            curr.execute("""
                CREATE TABLE IF NOT EXISTS daily_sentences_deepseek (
                        id SERIAL PRIMARY KEY,
                        date DATE NOT NULL DEFAULT CURRENT_DATE,
                        sentence TEXT NOT NULL,
                        unique_id INT NOT NULL,
                        user_id BIGINT,
                        session_id BIGINT,
                        id_for_mistake_table INT
                );
            """)

            # ✅ Таблица user_progress
            curr.execute("""
                CREATE TABLE IF NOT EXISTS user_progress_deepseek (
                    session_id BIGINT PRIMARY KEY,
                    user_id BIGINT,
                    username TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    completed BOOLEAN DEFAULT FALSE,
                    CONSTRAINT unique_user_session_deepseek UNIQUE (user_id, start_time)
                );
            """)

            # ✅ Таблица для хранения ошибок перевода
            curr.execute("""
                CREATE TABLE IF NOT EXISTS translation_errors_deepseek (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        category TEXT NOT NULL CHECK (category IN ('Грамматика', 'Лексика', 'Падежи', 'Орфография', 'Синтаксис')),  
                        error_description TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # ✅ Таблица для хранения запасных предложений в случае отсутствия связи Или ошибки на стороне Open AI API
            curr.execute("""
                CREATE TABLE IF NOT EXISTS spare_sentences_deepseek (
                    id SERIAL PRIMARY KEY,
                    sentence TEXT NOT NULL
                );
                         
            """)


            # таблица для хранения id assistant API Open AI
            curr.execute("""
                CREATE TABLE IF NOT EXISTS assistants(
                    task_name TEXT PRIMARY KEY,
                    assistant_id TEXT NOT NULL
                    );
            """)


            # ✅ Таблица для хранения ошибок
            curr.execute("""
                    CREATE TABLE IF NOT EXISTS detailed_mistakes_deepseek (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        sentence TEXT NOT NULL,
                        added_data TIMESTAMP,
                        main_category TEXT CHECK (main_category IN (
                            -- 🔹 Nouns
                            'Nouns', 'Cases', 'Verbs', 'Tenses', 'Adjectives', 'Adverbs', 
                            'Conjunctions', 'Prepositions', 'Moods', 'Word Order', 'Other mistake'
                        )),  
                        sub_category TEXT CHECK (sub_category IN (
                            -- 🔹 Nouns
                            'Gendered Articles', 'Pluralization', 'Compound Nouns', 'Declension Errors',
                            
                            -- 🔹 Cases
                            'Nominative', 'Accusative', 'Dative', 'Genitive',
                            'Akkusativ + Preposition', 'Dative + Preposition', 'Genitive + Preposition',
                            
                            -- 🔹 Verbs
                            'Placement', 'Conjugation', 'Weak Verbs', 'Strong Verbs', 'Mixed Verbs', 
                            'Separable Verbs', 'Reflexive Verbs', 'Auxiliary Verbs', 'Modal Verbs',
                            'Verb Placement in Subordinate Clause',
                            
                            -- 🔹 Tenses
                            'Present', 'Past', 'Simple Past', 'Present Perfect', 
                            'Past Perfect', 'Future', 'Future 1', 'Future 2',
                            'Plusquamperfekt Passive', 'Futur 1 Passive', 'Futur 2 Passive',

                            -- 🔹 Adjectives
                            'Endings', 'Weak Declension', 'Strong Declension', 'Mixed Declension', 
                            'Placement', 'Comparative', 'Superlative', 'Incorrect Adjective Case Agreement',

                            -- 🔹 Adverbs
                            'Placement', 'Multiple Adverbs', 'Incorrect Adverb Usage',

                            -- 🔹 Conjunctions
                            'Coordinating', 'Subordinating', 'Incorrect Use of Conjunctions',

                            -- 🔹 Prepositions
                            'Accusative', 'Dative', 'Genitive', 'Two-way',
                            'Incorrect Preposition Usage',

                            -- 🔹 Moods
                            'Indicative', 'Declarative', 'Interrogative', 'Imperative',
                            'Subjunctive 1', 'Subjunctive 2',

                            -- 🔹 Word Order
                            'Standard', 'Inverted', 'Verb-Second Rule', 'Position of Negation',
                            'Incorrect Order in Subordinate Clause', 'Incorrect Order with Modal Verb',

                            -- 🔹 Other
                            'Unclassified mistake' -- Для ошибок, которые не попали в категории
                        )),
                        
                        mistake_count INT DEFAULT 1, -- Количество раз, когда ошибка была зафиксирована
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Время первой фиксации ошибки
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Время последнего появления ошибки
                        error_count_week INT DEFAULT 0, -- Количество ошибок за последнюю неделю
                        sentence_id INT,
                        correct_translation TEXT NOT NULL,
                        score INT,
                        attempt INT DEFAULT 1,

                        -- ✅ Уникальный ключ для предотвращения дубликатов
                        CONSTRAINT for_mistakes_table UNIQUE (user_id, sentence, main_category, sub_category)
                    );

            """)
                         
    connection.commit()

    print("✅ Таблицы sentences_deepseek, translations_deepseek, daily_sentences_deepseek, messages_deepseek, user_progress_deepseek, translation_errors_deepseek проверены и готовы к использованию.")

initialise_database()

async def log_all_messages(update: Update, context: CallbackContext):
    """Логируем ВСЕ текстовые сообщения для отладки."""
    try:
        if update.message and update.message.text:
            logging.info(f"📩 Бот получил сообщение: {update.message.text}")
        else:
            logging.warning("⚠️ update.message отсутствует или пустое.")
    except Exception as e:
        logging.error(f"❌ Ошибка логирования сообщения: {e}")
    

# Функция для добавления в словарь всех id Сообщений которые потом я буду удалять, Это служебные сообщения вспомогательные
def add_service_msg_id(context, message_id):
    context_id = id(context)
    logging.info(f"DEBUG: context_id={context_id} в add_service_msg_id, добавляем message_id={message_id}")
    if "service_message_ids" not in context.user_data:
        logging.info(f"📝 Создаём service_message_ids для user_id={context._user_id}")
        context.user_data["service_message_ids"] = []
    context.user_data["service_message_ids"].append(message_id)
    logging.info(f"DEBUG: Добавлен message_id: {message_id}, текущий список: {context.user_data['service_message_ids']}")


#Имитация набора текста с typing-индикатором
async def simulate_typing(context, chat_id, duration=3):
    """Эмулирует набор текста в чате."""
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    await asyncio.sleep(duration)  # Имитация задержки перед отправкой текста



# Buttons in Telegram
async def send_main_menu(update: Update, context: CallbackContext):
    """Принудительно обновляет главное меню с кнопками."""
    keyboard = [
        ["📌 Выбрать тему"],  # ❗ Убедись, что текст здесь правильный
        ["🚀 Начать перевод", "✅ Завершить перевод"],
        ["📜 Проверить перевод", "🟡 Посмотреть свою статистику"]
    ]
    
    # создаем в словаре клю service_message_ids Список для хранения всех id Сообщений, Для того чтобы потом можно было их удалить после выполнения перевода
    context.user_data.setdefault("service_message_ids", [])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    # 1️⃣ Удаляем старую клавиатуру
    #await update.message.reply_text("⏳ Обновляем меню...", reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True))

    # 2️⃣ Отправляем новое меню
    await update.message.reply_text("Используйте кнопки:", reply_markup=reply_markup)

async def debug_message_handler(update: Update, context: CallbackContext):
    print(f"🔹 Получено сообщение (DEBUG): {update.message.text}")


async def handle_button_click(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на кнопки главного меню."""
    
    print("🛠 handle_button_click() вызван!")  # Логируем сам вызов функции

    if not update.message:
        print("❌ Ошибка: update.message отсутствует!")
        return
    
    text = update.message.text.strip()
    print(f"📥 Получено сообщение: {text}")

    # Добавляем message_id пользовательского сообщения в список сервисных сообщений
    add_service_msg_id(context, update.message.message_id)
    logging.info(f"📩 Добавлен message_id пользовательского сообщения: {update.message.message_id}")
    
    if text == "📌 Выбрать тему":
        await choose_topic(update, context)
    elif text == "🚀 Начать перевод":
        await letsgo(update, context)
    elif text == "✅ Завершить перевод":
        await done(update, context)
    elif text == "🟡 Посмотреть свою статистику":
        await user_stats(update, context)
    elif text == "📜 Проверить перевод":
        logging.info(f"📌 Пользователь {update.message.from_user.id} нажал кнопку '📜 Проверить перевод'. Запускаем проверку.")
        await check_translation_from_text(update, context)  # ✅ Теперь сразу запускаем проверку переводов


# 🔹 **Функция, которая запускает проверку переводов**
async def check_translation_from_text(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    # Проверяем, есть ли накопленные переводы
    if "pending_translations" not in context.user_data or not context.user_data["pending_translations"]:
        logging.info(f"❌ Пользователь {user_id} нажал '📜 Проверить перевод', но у него нет сохранённых переводов!")
        msg_1 = await update.message.reply_text("❌ У вас нет непроверенных переводов! Сначала отправьте перевод, затем нажмите '📜 Проверить перевод'.")
        logging.info(f"📩 Отправлено сообщение об отсутствии переводов с ID={msg_1.message_id}")
        add_service_msg_id(context, msg_1.message_id)
        return

    logging.info(f"📌 Пользователь {user_id} нажал кнопку '📜 Проверить перевод'. Запускаем проверку переводов.")

    # ✅ Формируем переводы в нужном формате (чтобы избежать ошибки "неверный формат")
    formatted_translations = []
    for t in context.user_data["pending_translations"]:
        match = re.match(r"^(\d+)\.\s*(.+)", t)  # Извлекаем номер и перевод
        if match:
            formatted_translations.append(f"{match.group(1)}. {match.group(2)}")

    # Если нет отформатированных переводов, выдаём ошибку
    if not formatted_translations:
        msg_2 = await update.message.reply_text("❌ Ошибка: Нет переводов для проверки!")
        logging.info(f"📩 Отправлено сообщение об отсутствии переводов for translation с ID={msg_2.message_id}")
        add_service_msg_id(context, msg_2.message_id)
        return

    # ✅ Формируем команду "/translate" с нужным форматом
    translation_text = "/translate\n" + "\n".join(formatted_translations)

    # ✅ Очищаем список ожидающих переводов (чтобы повторно не сохранялись)
    #context.user_data["pending_translations"] = []

    # ✅ Логируем перед передачей в `check_user_translation()`
    logging.info(f"📜 Передаём в check_user_translation():\n{translation_text}")

    # ✅ Отправляем текст в `check_user_translation()`
    await check_user_translation(update, context, translation_text)

    

async def start(update: Update, context: CallbackContext):
    """Запуск бота и отправка главного меню."""
    context.user_data.setdefault("service_message_ids", [])  # Инициализируем список
    await send_main_menu(update, context)

async def log_message(update: Update, context: CallbackContext):
    """логируются (сохраняются) все сообщения пользователей в базе данных"""
    if not update.message: #Если update.message отсутствует, значит, пользователь отправил что-то другое (например, фото, видео, стикер).
        return #В таком случае мы не логируем это и просто выходим из функции
    
    user = update.message.from_user # Данные о пользователе содержит ID и имя пользователя.
    message_text = update.message.text.strip() if update.message else "" #сам текст сообщения.

    if not message_text:
        print("⚠️ Пустое сообщение — пропускаем логирование.")
        return
    
    username = user.username or f"{user.first_name or ''} {user.last_name or ''}".strip()
    # Логируем данные для диагностики
    print(f"📥 Получено сообщение от {username} ({user.id}): {message_text}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try: 
        cursor.execute("""
            INSERT INTO messages_deepseek (user_id, username, message)
            VALUES(%s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET timestamp = NOW();
            """,
            (user.id, username, 'user_message')
        )

        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка при записи в базу: {e}")
    finally:
        cursor.close()
        conn.close()

# утреннее приветствие членом группы
async def send_morning_reminder(context:CallbackContext):
    time_now= datetime.now().time()
    # Формируем утреннее сообщение
    message = (
        f"🌅 {'Доброе утро' if time(2, 0) < time_now < time(10, 0) else ('Добрый день' if time(10, 1) < time_now < time(17, 0) else 'Добрый вечер')}!\n\n"
        "Чтобы принять участие в переводе, нажмите на кнопку 📌 Выбрать тему. После выбора темы подтвердите начало с помощью кнопки 🚀 Начать перевод.\n\n"
        "📌 Важно:\n"
        "🔹 Переводите максимально точно и быстро.\n\n"
        "🔹 После перевода всех предложений выполните 📜 Проверить перевод и подтвердите нажатием ✅ Завершить перевод.\n\n"
        "🔹 В 09:05, 14:05 и 18:05 - промежуточные итоги по каждому участнику.\n\n"
        "🔹 Итоговые результаты получим в 22:52.\n\n"
        "🔹 Узнать свою статистику - жми 🟡 Посмотреть свою статистику.\n"
    )

    # формируем список команд
    commands = (
        "📜 **Доступные команды:**\n"
        "📌 Выбрать тему - Выбрать тему для перевода\n"
        "🚀 Начать перевод - Получить предложение для перевода после выбора темы.\n"
        "📜 Проверить перевод - После отправки предложений, проверить перевод\n"
        "✅ Завершить перевод - Завершить перевод и зафиксировать время.\n"
        "/stats - Узнать свою статистику\n"
    )

    await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text = message)
    #await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text= commands)



async def letsgo(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_id = user.id
    chat_id = update.message.chat_id  # ✅ Исправленный атрибут
    username = user.username or user.first_name

    context.user_data.setdefault("service_message_ids", [])

     # ✅ Если словаря `start_times` нет — создаём его (это может быть в начале запуска бота, Когда ещё нет словаря)
    if "start_times" not in context.user_data:
        context.user_data["start_times"] = {}
    
    # ✅ Запоминаем время старта **для конкретного пользователя**
    context.user_data["start_times"][user_id] = datetime.now()

    # # ✅ Отправляем сообщение с таймером
    # timer_message = await update.message.reply_text(f"⏳ Время перевода: 0 мин 0 сек")

    # # ✅ Запускаем `start_timer()` с правильными аргументами
    # asyncio.create_task(start_timer(chat_id, context, timer_message.message_id, user_id))


    # 🔹 Проверяем, выбрал ли пользователь тему
    chosen_topic = context.user_data.get("chosen_topic")
    if not chosen_topic:
        msg_1 = await update.message.reply_text(
            "❌ Вы не выбрали тему! Сначала выберите тему используя кнопку '📌 Выбрать тему'"
        )
        logging.info(f"📩 Отправлено сообщение об ошибке темы с ID={msg_1.message_id}")
        add_service_msg_id(context, msg_1.message_id)
        return  # ⛔ Прерываем выполнение функции, если тема не выбрана

    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем, не запустил ли уже пользователь перевод (но только за СЕГОДНЯ!)
    cursor.execute("""
        SELECT user_id FROM user_progress_deepseek
        WHERE user_id = %s AND start_time::date = CURRENT_DATE AND completed = FALSE;
        """, (user_id, ))
    active_session = cursor.fetchone()

    if active_session is not None:
        logging.info(f"⏳ Пользователь {username} ({user_id}) уже начал перевод сегодня.")
        #await update.message.reply_animation("https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif")
        msg_2 = await update.message.reply_text("❌ Вы уже начали перевод! Завершите его перед повторным запуском нажав на кнопку '✅ Завершить перевод'")
        logging.info(f"📩 Отправлено сообщение об активной сессии с ID={msg_2.message_id}")
        add_service_msg_id(context, msg_2.message_id)
        cursor.close()
        conn.close()
        return

    # ✅ **Автоматически завершаем вчерашние сессии**
    cursor.execute("""
        UPDATE user_progress_deepseek
        SET end_time = NOW(), completed = TRUE
        WHERE user_id = %s AND start_time::date < CURRENT_DATE AND completed = FALSE;
    """, (user_id,))

    # 🔹 Генерируем session_id на основе user_id + текущего времени
    session_id = int(hashlib.md5(f"{user_id}{datetime.now()}".encode()).hexdigest(), 16) % (10 ** 12)

    # ✅ **Создаём новую запись в `user_progress`, НЕ ЗАТИРАЯ старые сессии и получаем `session_id`****
    cursor.execute("""
        INSERT INTO user_progress_deepseek (session_id, user_id, username, start_time, completed) 
        VALUES (%s, %s, %s, NOW(), FALSE);
    """, (session_id, user_id, username))
    
    conn.commit()


    # ✅ **Выдаём новые предложения**
    sentences = [s.strip() for s in await get_original_sentences(user_id, context) if s.strip()]

    if not sentences:
        msg_3 = await update.message.reply_text("❌ Ошибка: не удалось получить предложения. Попробуйте позже.")
        logging.info(f"📩 Отправлено сообщение: ❌ Ошибка: не удалось получить предложения. Попробуйте позже с ID={msg_3.message_id}")
        add_service_msg_id(context, msg_3.message_id)       
        cursor.close()
        conn.close()
        return

    # Определяем стартовый индекс (если пользователь делал /getmore)
    cursor.execute("""
        SELECT COUNT(*) FROM daily_sentences_deepseek WHERE date = CURRENT_DATE AND user_id = %s;
    """, (user_id,))
    last_index = cursor.fetchone()[0]

    # Добавляем логирование, чтобы видеть, были ли исправления
    original_sentences = sentences
    sentences = correct_numbering(sentences)

    for before, after in zip(original_sentences, sentences):
        if before != after:
            logging.info(f"⚠️ Исправлена нумерация: '{before}' → '{after}'")

    # Записываем bсе предложения в базу
    tasks = []

    for i, sentence in enumerate(sentences, start=last_index+1):
        # ✅ Проверяем, есть ли уже предложение с таким текстом
        cursor.execute("""
            SELECT id_for_mistake_table
            FROM daily_sentences_deepseek
            WHERE sentence = %s
            LIMIT 1;
        """, (sentence, ))
        result = cursor.fetchone()

        if result:
            id_for_mistake_table = result[0]
            logging.info(f"✅ Найден существующий id_for_mistake_table = {id_for_mistake_table} для текста: '{sentence}'")
        else:
            # ✅ Если текста нет — получаем максимальный ID и создаём новый
            cursor.execute("""
                SELECT MAX(id_for_mistake_table) FROM daily_sentences_deepseek;
            """)
            result = cursor.fetchone()
            max_id = result[0] if result and result[0] is not None else 0
            id_for_mistake_table = max_id + 1
            logging.info(f"✅ Присваиваем новый id_for_mistake_table = {id_for_mistake_table} для текста: '{sentence}'")

        # ✅ Вставляем предложение в таблицу с id_for_mistake_table
        cursor.execute("""
            INSERT INTO daily_sentences_deepseek (date, sentence, unique_id, user_id, session_id, id_for_mistake_table)
            VALUES (CURRENT_DATE, %s, %s, %s, %s, %s);
        """, (sentence, i, user_id, session_id, id_for_mistake_table))
        
        tasks.append(f"{i}. {sentence}")

    conn.commit()
    cursor.close()
    conn.close()

    logging.info(f"🚀 Пользователь {username} ({user_id}) начал перевод. Записано {len(tasks)} предложений.")

    # 🔹 **Создаём пустой список для переводов пользователя**
    context.user_data["pending_translations"] = []


    # ✅ Отправляем одно сообщение с предложениями **и таймером**
    task_text = "\n".join(tasks)
    print(f"Sentences before sending to the user: {task_text}")

    text= (
    f"🚀 {user.first_name}, Вы начали перевод! Время пошло.\n\n"
    "✏️ Отправьте ваши переводы в формате:\n1. Mein Name ist Konchita.\n\n"
    )

    msg_4 = await context.bot.send_message(chat_id=update.message.chat_id, text=text)
    logging.info(f"📩 Отправлено сообщение о начале перевода с ID={msg_4.message_id}")
    add_service_msg_id(context, msg_4.message_id)

    msg_5 = await update.message.reply_text(
        f"{user.first_name}, Ваши предложения:\n{task_text}\n\n"
        #"После того как вы отправите все переводы, нажмите **'📜 Проверить перевод'**, чтобы проверить их.\n"
        #"Когда все переводы будут проверены, нажмите **'✅ Завершить перевод'**, чтобы зафиксировать время!"
    )
    logging.info(f"📩 Отправлено сообщение с предложениями с ID={msg_5.message_id}")
    add_service_msg_id(context, msg_5.message_id)



# 🔹 **Функция, которая запоминает переводы, но не проверяет их**
async def handle_user_message(update: Update, context: CallbackContext):
    # ✅ Проверяем, содержит ли update.message данные
    if update.message is None or update.message.text is None:
        logging.warning("⚠️ update.message отсутствует или пустое.")
        return  # ⛔ Прерываем выполнение, если сообщение отсутствует

    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Проверяем, является ли сообщение переводом (поддержка многострочных сообщений)
    pattern = re.compile(r"^(\d+)\.\s*([^\d\n]+(?:\n[^\d\n]+)*)", re.MULTILINE)
    translations = pattern.findall(text)

    if translations:
        if "pending_translations" not in context.user_data:
            context.user_data["pending_translations"] = []

        for num, trans in translations:
            full_translation = f"{num}. {trans.strip()}"
            context.user_data["pending_translations"].append(full_translation)
            logging.info(f"📝 Добавлен перевод: {full_translation}")

        msg = await update.message.reply_text(
            "✅ Ваш перевод сохранён.\n\n"
            "Когда будете готовы, нажмите:\n"
            "📜 Проверить перевод.\n\n"
            "✅ Завершить перевод чтобы зафиксировать время.\n"
            )
        add_service_msg_id(context, msg.message_id)
    else:
        await handle_button_click(update, context)


async def delete_message_with_retry(bot, chat_id, message_id, retries=3, delay=2):
    for attempt in range(retries):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            print(f"DEBUG: Успешно удалено сообщение {message_id}")
            return
        except TimedOut as e:
            print(f"❌ Таймаут при удалении сообщения {message_id} (попытка {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        except BadRequest as e:
            print(f"❌ Ошибка Telegram при удалении сообщения {message_id}: {e}")
            return  # Сообщение не существует или уже удалено
        except Exception as e:
            print(f"❌ Неизвестная ошибка при удалении сообщения {message_id}: {e}")
            return
    print(f"❌ Не удалось удалить сообщение {message_id} после {retries} попыток")


async def done(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_id = user.id
    context_id = id(context)
    logging.info(f"DEBUG: context_id={context_id} в done")


    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Проверяем, есть ли у пользователя активная сессия
    cursor.execute("""
        SELECT session_id
        FROM user_progress_deepseek 
        WHERE user_id = %s AND completed = FALSE
        ORDER BY start_time DESC
        LIMIT 1;""", 
        (user_id,))
    session = cursor.fetchone()

    if not session:
        msg_1 = await update.message.reply_text("❌ У вас нет активных сессий! Используйте кнопки: '📌 Выбрать тему' -> '🚀 Начать перевод' чтобы начать.")
        logging.info(f"📩 Отправлено сообщение об отсутствии сессии с ID={msg_1.message_id}")
        add_service_msg_id(context, msg_1.message_id)
        cursor.close()
        conn.close()
        return
    session_id = session[0]   # ID текущей сессии

    # 📊 Получаем общее количество предложений
    cursor.execute("""
        SELECT COUNT(*) 
        FROM daily_sentences_deepseek 
        WHERE user_id = %s AND session_id = %s;
        """, (user_id, session_id))
    
    total_sentences = cursor.fetchone()[0]
    logging.info(f"🔄 Ожидаем записи всех переводов пользователя {user_id}. Всего предложений: {total_sentences}")

    # Получаем количество отправленных переводов (из pending_translations)
    pending_translations_count = len(context.user_data.get("pending_translations", []))
    logging.info(f"📤 Пользователь отправил переводов: {pending_translations_count}")

    # Даем время для завершения асинхронных задач (например, записи переводов из check_translation_from_text)
    logging.info("⏳ Даем время для завершения записи переводов в базу...")
    await asyncio.sleep(5)  # Задержка 5 секунд перед первой проверкой

    # Получаем количество записанных переводов в базе
    cursor.execute("""
        SELECT COUNT(*) 
        FROM translations_deepseek 
        WHERE user_id = %s AND session_id = %s;
        """, (user_id, session_id))
    translated_count = cursor.fetchone()[0]
    logging.info(f"📬 Уже записано переводов: {translated_count}/{pending_translations_count}")


    # Проверяем, если отправленных переводов больше, чем предложений в сессии
    if pending_translations_count > total_sentences:
        logging.warning(f"⚠️ pending_translations_count ({pending_translations_count}) больше total_sentences ({total_sentences})")
        pending_translations_count = min(pending_translations_count, total_sentences)

    #await asyncio.sleep(10)


    # Ожидаем, пока все отправленные переводы не запишутся в базу
    max_attempts = 30  # Максимум 30 попыток (30 * 5 секунд = 150 секунд)
    attempt = 0
    start_time = datetime.now()

    logging.info(f"🚩 START while-loop: translated_count={translated_count}, pending_translations_count={pending_translations_count}")

    while translated_count < pending_translations_count and attempt < max_attempts:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM translations_deepseek 
            WHERE user_id = %s AND session_id = %s;
            """, (user_id, session_id))
        translated_count = cursor.fetchone()[0]
        elapsed_time = (datetime.now() - start_time).total_seconds()
        logging.info(f"⌛ Проверяем запись переводов: {translated_count}/{pending_translations_count}. Прошло {elapsed_time:.1f} сек, попытка {attempt + 1}")

        if translated_count >= pending_translations_count:
            logging.info(f"✅ Все отправленные переводы записаны: {translated_count}/{pending_translations_count}")
            break

        await asyncio.sleep(5)  # Ждем 5 секунд
        attempt += 1

    # Логируем, если не все переводы записаны
    if translated_count < pending_translations_count and attempt >= max_attempts:
        logging.warning(f"⚠️ Не все переводы записаны после {max_attempts} попыток: {translated_count}/{pending_translations_count}")


    # Завершаем сессию
    cursor.execute("""
        UPDATE user_progress_deepseek
        SET end_time = NOW(), completed = TRUE
        WHERE user_id = %s AND session_id = %s AND completed = FALSE;
        """, (user_id, session_id))
    conn.commit()

    # Сбрасываем pending_translations
    context.user_data["pending_translations"] = []
    logging.info(f"DEBUG: Сброшены pending_translations для user_id={user_id}")

    # Отправляем итоговое сообщение пользователю
    if translated_count == 0:
        completion_msg = await update.message.reply_text(
            f"😔 Вы не перевели ни одного предложения из {total_sentences} в этой сессии.\n"
            f"Попробуйте начать новую сессию с помощью кнопок '📌 Выбрать тему' -> '🚀 Начать перевод'.",
            parse_mode="Markdown"
        )
    elif translated_count < total_sentences:
        completion_msg = await update.message.reply_text(
            f"⚠️ *Вы перевели {translated_count} из {total_sentences} предложений!*\n"
            f"Перевод завершён, но не все предложения переведены. Это повлияет на ваш итоговый балл.",
            parse_mode="Markdown"
        )
    else:
        completion_msg = await update.message.reply_text(
            f"🎉 *Вы успешно завершили перевод!*\n"
            f"Все {total_sentences} предложений этой сессии переведены! 🚀",
            parse_mode="Markdown"
        )
    
    message_ids = context.user_data.get("service_message_ids", [])
    
    # Deletion messages from the chat
    for message_id in message_ids:
        await delete_message_with_retry(context.bot, update.effective_chat.id, message_id)

    # Сбрасываем список
    logging.info(f"DEBUG: Сбрасываем service_message_ids. Было: {context.user_data['service_message_ids']}")
    context.user_data["service_message_ids"] = []

    cursor.close()
    conn.close()


def correct_numbering(sentences):
    """!?! Но это выражение требует фиксированный длины шаблона внутри скобок(?<=^\d+\.), Поэтому не подходит.Исправляет нумерацию, удаляя только вторую некорректную цифру.
    (?<=^\d+\.) — Найди совпадение, но только если перед ним есть число с точкой в начале строки
    Это называется lookbehind assertion. Например, 29. будет найдено, но не заменено.
    \s*\d+\.\s* — теперь заменяется только вторая цифра."""
    corrected_sentences = []
    for sentence in sentences:
        # Удаляем только **второе** число, оставляя первое
        cleaned_sentence = re.sub(r"^(\d+)\.\s*\d+\.\s*", r"\1. ", sentence).strip()
        corrected_sentences.append(cleaned_sentence)
    return corrected_sentences


# Создаёт кнопки с темами (Business, Medicine, Hobbies и т. д.).
async def choose_topic(update: Update, context: CallbackContext):
    print("🔹 Функция choose_topic() вызвана!")  # 👈 Логируем вызов
    global TOPICS
    
    context.user_data.setdefault("service_message_ids", [])
    message_ids = context.user_data["service_message_ids"]
    #message_ids = context.user_data.get("service_message_ids", [])
    print(f"DEBUG: message_ids in choose_topic function: {message_ids}")
    
    buttons = []
    row = []
    for i, topic in enumerate(TOPICS, 1):
        row.append(InlineKeyboardButton(topic, callback_data=topic))
        if i % 2 == 0:
            buttons.append(row)
            row = []
    if row:  # если остались кнопки, которые не кратны 3 (например 10 тем — 9 + 1)
        buttons.append(row)

    reply_markup = InlineKeyboardMarkup(buttons)

    if update.callback_query:
        msg = await update.callback_query.message.edit_text("📌 Выберите тему для предложений:", reply_markup=reply_markup)
        add_service_msg_id(context, msg.message_id)
    else:
        msg_1 = await update.message.reply_text("📌 Выберите тему для предложений:", reply_markup=reply_markup) #Отправляем сообщение пользователю с прикреплёнными кнопками.
        add_service_msg_id(context, msg_1.message_id)



# Когда пользователь нажимает на кнопку, Telegram отправляет callback-запрос, который мы обработаем в topic_selected().
async def topic_selected(update: Update, context: CallbackContext):
    """Handles the button click event when the user selects a topic."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press: Подтверждаем нажатие кнопки (иначе кнопка будет висеть)

    if not query.data:
        logging.error("❌ Ошибка: callback_data отсутствует!")
        return

    chosen_topic = query.data  # Get the selected topic: # Получаем данные (какую кнопку нажали)
    logging.info(f"✅ Пользователь выбрал тему: {chosen_topic}")

    context.user_data["chosen_topic"] = chosen_topic  # Store it in user data: # Сохраняем выбранную тему в памяти пользователя
    msg_1 = await query.message.reply_text(f"✅ Вы выбрали тему: {chosen_topic}.\nТеперь нажмите '🚀 Начать перевод'.")
    add_service_msg_id(context, msg_1.message_id)



# === Функция для генерации новых предложений с помощью GPT-4 ===
async def generate_sentences(user_id, num_sentances, context: CallbackContext = None):
    #client_deepseek = OpenAI(api_key = api_key_deepseek,base_url="https://api.deepseek.com")
    
    task_name = f"generate_sentences"
    system_instruction = f"generate_sentences"
    assistant_id, _ = get_or_create_openai_resources(system_instruction, task_name)
            
    # ✅ Создаём новый thread каждый раз
    thread = client.beta.threads.create()
    thread_id = thread.id

    chosen_topic = context.user_data.get("chosen_topic", "Random sentences")  # Default: General topic


    # if chosen_topic != "Random sentences":
    user_message = f"""
    Number of sentences: {num_sentances}. Topic: "{chosen_topic}".
    """

    #Генерация с помощью GPT     
    for attempt in range(5): # Пробуем до 5 раз при ошибке
        try:
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )

            run = client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            while True:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                if run_status.status == "completed":
                    break
                await asyncio.sleep(1)  # подожди чуть-чуть
            

            # Получаем сообщения после завершения run
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            last_message = messages.data[0]  # обычно последнее — ответ
            sentences = last_message.content[0].text.value

            try:
                client.beta.threads.delete(thread_id=thread_id)
                logging.info(f"🗑️ Thread удалён: {thread_id}")

            except Exception as e:
                logging.warning(f"Не удалось удалить thread: {e}")

            # response = await client.chat.completions.create(
            #     model = "gpt-4-turbo",
            #     messages = [{"role": "user", "content": prompt}]
            # )
            # sentences = response.choices[0].message.content.split("\n")
            filtered_sentences = [s.strip() for s in sentences.split("\n") if s.strip()] # ✅ Фильтруем пустые строки
            
            if filtered_sentences:
                return filtered_sentences
            
        except openai.RateLimitError:
            wait_time = (attempt +1) * 2 # Задержка: 2, 4, 6 сек...
            print(f"⚠️ OpenAI API Rate Limit. Ждем {wait_time} сек...")
            await asyncio.sleep(wait_time)
    
    print("❌ Ошибка: не удалось получить ответ от OpenAI. Используем запасные предложения.")


    # # Генерация с помощью DeepSeek API
    # for attempt in range(5): # Пробуем до 5 раз при ошибке
    #     try:
    #         response = await client_deepseek.chat.completions.create(
    #             model = "deepseek-chat",
    #             messages = [{"role": "user", "content": prompt}], stream=False
    #         )
    #         sentences = response.choices[0].message.content.split("\n")
    #         filtered_sentences = [s.strip() for s in sentences if s.strip()] # ✅ Фильтруем пустые строки
    #         if filtered_sentences:
    #             return filtered_sentences
    #     except openai.RateLimitError:
    #         wait_time = (attempt +1) * 2 # Задержка: 2, 4, 6 сек...
    #         print(f"⚠️ OpenAI API Rate Limit. Ждем {wait_time} сек...")
    #         await asyncio.sleep(wait_time)
    
    # print("❌ Ошибка: не удалось получить ответ от OpenAI. Используем запасные предложения.")


    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT sentence FROM spare_sentences_deepseek ORDER BY RANDOM() LIMIT 7;""")
    spare_rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if spare_rows:
        return [row[0].strip() for row in spare_rows if row[0].strip()]
    else:
        print("❌ Ошибка: даже запасные предложения отсутствуют.")
        return ["Запасное предложение 1", "Запасное предложение 2"]


async def recheck_score_only(client_recheck, original_text, user_translation):
    prompt = f"""
You previously evaluated a student's translation and gave it a score of 0 out of 100.

Please reassess the score **again** based on the information below.

Original sentence (Russian): "{original_text}"  
User's translation (German): "{user_translation}"  

Return your reassessed score in the following format only:  
Score: X/100
""" 
    for i in range(3):
        try:
            responce = await client_recheck.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            text = responce.choices[0].message.content.strip()
            print(f"🔁 Ответ на перепроверку оценки:\n{text}")
            if "score" in text.lower():
                reassessed_score = text.lower().split("score:")[-1].split("/")[0].strip()
                try:
                    if int(reassessed_score) == 0:
                        continue
                    return reassessed_score
                except ValueError:
                    print(f"⚠️ Не удалось привести reassessed_score к числу: {reassessed_score}")
                    continue

        except Exception as e:
            print(f"❌ Ошибка при перепроверке score: {e}")
            continue
        
    return "0" # fallback, если GPT не ответил


async def check_translation(original_text, user_translation, update: Update, context: CallbackContext, sentence_number):
    client_recheck = openai.AsyncOpenAI(api_key=openai.api_key)
    task_name = f"check_translation"
    system_instruction = f"check_translation"
    assistant_id, _ = get_or_create_openai_resources(system_instruction, task_name)
            
    # ✅ Создаём новый thread каждый раз
    thread = client.beta.threads.create()
    thread_id = thread.id

    # Initialize variables with default values at the beginning of the function
    score = "50"  # Default score
    categories = []
    subcategories = []
    correct_translation = "there is no information."  # Default translation
    
    # ✅ Показываем сообщение о начале проверки
    message = await context.bot.send_message(chat_id=update.message.chat_id, text="⏳ Посмотрим на что ты способен...")
    
    await simulate_typing(context, update.message.chat_id, duration=3)

    user_message = f"""

    **Original sentence (Russian):** "{original_text}"
    **User's translation (German):** "{user_translation}"

    """

    for attempt in range(3):
        try:
            logging.info(f" GPT started working on {original_text} sentence. Passing data to GPT model")
            start_time = asyncio.get_running_loop().time()
            
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )

            run = client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            while True:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                if run_status.status == "completed":
                    break
                await asyncio.sleep(2)  # подожди чуть-чуть


            # Получаем сообщения после завершения run
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            last_message = messages.data[0]  # обычно последнее — ответ
            collected_text = last_message.content[0].text.value
            logging.info(f"We got a reply from GPT model for sentence {original_text}")
            
            try:
                client.beta.threads.delete(thread_id=thread_id)
                logging.info(f"🗑️ Thread удалён: {thread_id}")

            except Exception as e:
                logging.warning(f"Не удалось удалить thread: {e}")
                

            # ✅ Логируем полный ответ для анализа
            print(f"🔎 FULL RESPONSE:\n{collected_text}")


            # ✅ Парсим результат
            score_str = collected_text.split("Score: ")[-1].split("/")[0].strip() if "Score:" in collected_text else None
            
            #my offer to split by ", " because it is a string and take all list
            # ✅ Ограничиваем строку до конца строки с помощью split("\n")[0]
            categories = collected_text.split("Mistake Categories: ")[-1].split("\n")[0].split(", ") if "Mistake Categories:" in collected_text else []
            subcategories = collected_text.split("Subcategories: ")[-1].split("\n")[0].split(", ") if "Subcategories:" in collected_text else []

            #severity = collected_text.split("Severity: ")[-1].split("\n")[0].strip() if "Severity:" in collected_text and len(collected_text.split("Severity: ")[-1].split("\n")) > 0 else None
            
            #correct_translation = collected_text.split("Correct Translation: ")[-1].strip() if "Correct Translation:" in collected_text else None
            correct_translation = None
            match = re.search(r'Correct Translation:\s*(.+?)(?:\n|\Z)', collected_text)
            if match:
                correct_translation = match.group(1).strip()
            
            # ✅ Логируем До обработки
            print(f"🔎 RAW CATEGORIES BEFORE HANDLING in check_translation function (User {update.message.from_user.id}): {', '.join(categories)}")
            print(f"🔎 RAW SUBCATEGORIES BEFORE HANDLING in check_translation function (User {update.message.from_user.id}): {', '.join(subcategories)}")
            
            # my offer for category: i would reduce all unneccessary symbols not only ** except from words and commas (what do you think!?)
            categories = [re.sub(r"[^0-9a-zA-Z\s,+\-–]", "", cat).strip() for cat in categories if cat.strip()]
            # my offer for subcategory: i would reduce all unneccessary symbols not only ** except from words and commas (what do you think!?)
            subcategories = [re.sub(r"[^0-9a-zA-Z\s,+\-–]", "", subcat).strip() for subcat in subcategories if subcat.strip()]

            # ✅ Преобразуем строки в списки: my offer
            categories = [cat.strip() for cat in categories if cat.strip()]
            subcategories = [subcat.strip() for subcat in subcategories if subcat.strip()]

            # ✅ Логируем
            print(f"🔎 RAW CATEGORIES AFTER HANDLING in check_translation function (User {update.message.from_user.id}): {', '.join(categories)}")
            print(f"🔎 RAW SUBCATEGORIES AFRET HANDLING (User {update.message.from_user.id}): {', '.join(subcategories)}")

            
            if not categories:
                print(f"⚠️ Категории отсутствуют в ответе GPT")
            if not subcategories:
                print(f"⚠️ Подкатегории отсутствуют в ответе GPT")

            if score_str and correct_translation:
                try:
                    score_int = int(score_str)
                except ValueError:
                    print(f"⚠️ Не удалось привести score_str к числу: {score_str}")
                    print(f"⚠️ GPT вернул некорректный формат оценки. Запрашиваем повторную оценку...")
                    reassessed_score = await recheck_score_only(client_recheck, original_text, user_translation)
                    print(f"🔁 GPT повторно оценил на: {reassessed_score}/100")
                    score = reassessed_score
                    break  # завершаем цикл успешно

                if score_int == 0:
                    print(f"⚠️ GPT поставил 0. Запрашиваем повторную оценку...")
                    reassessed_score = await recheck_score_only(client_recheck, original_text, user_translation)
                    print(f"🔁 GPT повторно оценил на: {reassessed_score}/100")
                    score = reassessed_score
                    break

                score = score_str
                print(f"✅ Успешно получены все обязательные данные на попытке {attempt + 1}")
                break
            
            else:
                missing_fields = []
                if not score_str:
                    missing_fields.append("Score")
                #if not severity:
                #    missing_fields.append("Severity")
                if not correct_translation:
                    missing_fields.append("Correct Translation")
                print(f"⚠️ Не получены обязательные поля: {', '.join(missing_fields)}. Повторяем запрос...")
                raise ValueError(f"Missing required fields: "
                     f"{'Score' if not score_str else ''} "
                     f"{'Correct Translation' if not correct_translation else ''}")


        except openai.RateLimitError:
            wait_time = (attempt + 1) * 5
            print(f"⚠️ OpenAI API перегружен. Ждём {wait_time} сек...")
            await asyncio.sleep(wait_time)

        except Exception as e:
            logging.error(f"❌ Ошибка: {e}")
            print(f"❌ Ошибка в цикле обработки: {e}")
            await asyncio.sleep(5)


    # ✅ Убираем лишние пробелы для ровного форматирования
    result_text = f"""
🟢 *Sentence number:* {sentence_number}\n
✅ *Score:* {score}/100\n
🔵 *Original Sentence:* {original_text}\n
🟡 *User Translation:* {user_translation}\n
🟣 *Correct Translation:* {correct_translation}\n
"""

    # ✅ Если балл > 75 → стилистическая ошибка
    if score and score.isdigit() and int(score) > 75:
        result_text += "\n✅ Перевод на высоком уровне — считаем это незначительной ошибкой."

    # ✅ Отправляем текст в Telegram с поддержкой HTML
    sent_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=escape_html_with_bold(result_text),
        parse_mode="HTML"
    )

    message_id = sent_message.message_id
    
    # ✅ Сохраняем данные в context.user_data
    if len(context.user_data) >= 10:
        oldest_key = next(iter(context.user_data))
        del context.user_data[oldest_key]  # Удаляем самые старые данные

    context.user_data[f"translation_{message_id}"] = {
        "original_text": original_text,
        "user_translation": user_translation
    }

    # ✅ Удаляем сообщение с индикатором "Генерация ответа"
    await message.delete()

    # ✅ Добавляем инлайн-кнопку после отправки сообщения
    keyboard = [[InlineKeyboardButton("❓ Explain me GPT", callback_data=f"explain:{message_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ✅ Задержка в 1,5 секунды для предотвращения блокировки
    await asyncio.sleep(1.5)

    # ✅ Редактируем сообщение, добавляем кнопку
    await sent_message.edit_text(
        text=escape_html_with_bold(result_text),
        reply_markup=reply_markup,
        parse_mode="HTML"
        )                        

    # ✅ Логируем успешную проверку
    logging.info(f"✅ Перевод проверен для пользователя {update.message.from_user.id}")

    return result_text, categories, subcategories, score, correct_translation


async def handle_explain_request(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()  # Подтверждаем получение запроса

    # ✅ Логируем факт вызова функции
    logging.info("🔹 handle_explain_request вызвана!")

    try:
        logging.info(f"🔹 Callback data: {query.data}")

        # ✅ Получаем `message_id` из callback_data
        message_id = int(query.data.split(":")[1])
        logging.info(f"✅ Извлечённый message_id: {message_id}")
        
        # Логируем сообщение, к которому пытаемся прикрепить комментарий
        chat_id = update.callback_query.message.chat_id

        # ✅ Логируем статус бота в чате
        member = await context.bot.get_chat_member(
            chat_id=chat_id,
            user_id=context.bot.id
        )
        if member.status in ['administrator', 'creator']:
            can_send_messages = True
        elif hasattr(member, 'can_send_messages'):
            can_send_messages = member.can_send_messages
        else:
            can_send_messages = False

        print(f"👮 Bot status: {member.status}, can_send_messages: {can_send_messages}")
        if not can_send_messages:
            logging.error("❌ Бот не имеет прав отправлять сообщения в этот чат!")
            await query.message.reply_text("❌ У бота нет прав отправлять сообщения в этот чат!")
            return


        #✅ Ищем в сохранённых данных
        data = context.user_data.get(f"translation_{message_id}")
        if not data:
            logging.error(f"❌ Данные для message_id {message_id} не найдены в context.user_data!")
            msg = await query.message.reply_text("❌ Данные перевода не найдены!")
            add_service_msg_id(context, msg.message_id)
            return       

        # ✅ Получаем текст оригинала и перевода
        original_text = data["original_text"]
        user_translation = data["user_translation"]
        # ✅ Запускаем объяснение с помощью Claude
        explanation = await check_translation_with_claude(original_text, user_translation, update, context)
        if not explanation:
            logging.error("❌ Не удалось получить объяснение от Claude!")
            msg_1 = await query.message.reply_text("❌ Не удалось получить объяснение!")
            add_service_msg_id(context, msg_1.message_id)
            return          
      
        # ✅ Логируем попытку отправки комментария
        print(f"📩 Sending reply to message with message_id: {message_id} in chat ID: {chat_id}")
        escaped_explanation = escape_html_with_bold(explanation)

        print(f"explanation from handle_explain_request_function before escape_html_with_bold: {explanation}")
        print(f"explanation from handle_explain_request_function after escape_html_with_bold: : {escaped_explanation}")

        # ✅ Отправляем ответ как комментарий к сообщению
        await context.bot.send_message(
            chat_id=chat_id,
            text=escaped_explanation,
            parse_mode="HTML",
            reply_to_message_id=message_id  # 🔥 ПРИКРЕПЛЯЕМСЯ К СООБЩЕНИЮ
            )
        
        # ✅ Удаляем данные после успешной обработки
        del context.user_data[f"translation_{message_id}"]
        print(f"✅ Удалены данные для message_id {message_id}")

    except TelegramError as e:
            if 'message to reply not found' in str(e).lower():
                print(f"⚠️ Message ID {message_id} not found — возможно, сообщение удалено!")
                await query.message.reply_text("❌ Сообщение не найдено, возможно, оно было удалено!")
            else:
                logging.error(f"❌ Telegram Error: {e}")
                await query.message.reply_text(f"❌ Ошибка Telegram: {e}")
    except Exception as e:
        logging.error(f"❌ Ошибка в handle_explain_request: {e}")
        await query.message.reply_text(f"❌ Произошла ошибка: {e}. Попробуйте повторить запрос.")




#✅ Explain with Claude
async def check_translation_with_claude(original_text, user_translation, update, context):
    task_name = f"check_translation_with_claude"
    system_instruction = f"check_translation_with_claude"
    assistant_id, _ = get_or_create_openai_resources(system_instruction, task_name)
            
    # ✅ Создаём новый thread каждый раз
    thread = client.beta.threads.create()
    thread_id = thread.id

    if update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
    else:
        logging.error("❌ Нет callback_query в update!")
        return None, None
    #this client is for Claude
    #client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

    user_message = f"""
    
    **Original sentence (Russian):** "{original_text}"
    **User's translation (German):** "{user_translation}"

    """
    #available_models = await client.models.list()
    # logging.info(f"📢 Available models: {available_models}")
    # print(f"📢 Available models: {available_models}")
    
    #model_name = "claude-3-7-sonnet-20250219"  
    
    for attempt in range(3):
        try:
            #it is correct working with Claude model
            # response = await client.messages.create(
            #     model=model_name,
            #     messages=[{"role": "user", "content": prompt}],
            #     max_tokens=500,
            #     temperature=0.2
            # )
            
            client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )

            run = client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id
            )
            while True:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                if run_status.status == "completed":
                    break
                await asyncio.sleep(1)  # подожди чуть-чуть
            

            # Получаем сообщения после завершения run
            messages = client.beta.threads.messages.list(thread_id=thread_id)
            last_message = messages.data[0]  # обычно последнее — ответ
            response = last_message.content[0].text.value

            try:
                client.beta.threads.delete(thread_id=thread_id)
                logging.info(f"🗑️ Thread удалён: {thread_id}")

            except Exception as e:
                logging.warning(f"Не удалось удалить thread: {e}")

            logging.info(f"📥 FULL RESPONSE BODY: {response}")

            if response:
                cloud_response = response
                #this is for the claude model
                #cloud_response = response.content[0].text
                break
            else:
                logging.warning("⚠️ Claude returned an empty response.")
                print("❌ Ошибка: Claude вернул пустой ответ. We will try one more time in 5 seconds")
                await asyncio.sleep(5)
        
        except anthropic.APIError as e:
            logging.error(f"❌ API Error from Claude: {e}")
            # Если ошибка действительно критическая — можно добавить проверку и выйти из цикла
            if "authentication" in str(e).lower() or "invalid token" in str(e).lower():
                logging.error("🚨 Критическая ошибка — завершаем цикл")
                break
            else:
                logging.warning("⚠️ Попробуем снова через 5 секунд...")
                await asyncio.sleep(5)

    else:
        print("❌ Ошибка: Пустой ответ от Claude после 3 попыток")
        return "❌ Ошибка: Не удалось обработать ответ от Claude."
    
    list_of_errors_pattern = re.findall(r'(Error)\s*(\d+)\:*\s*(.+?)(?:\n|$)', cloud_response, flags=re.DOTALL)

    correct_translation = re.findall(r'(Correct Translation)\:\s*(.+?)(?:\n|$)', cloud_response, flags=re.DOTALL)

    grammar_explanation_pattern = re.findall(r'(Grammar Explanation)\s*\:*\s*\n*(.+?)(?=\n[A-Z][a-zA-Z\s]+:|\Z)',cloud_response,flags=re.DOTALL | re.IGNORECASE)

    altern_sentence_pattern = re.findall(r'(Alternative Construction|Alternative Sentence Construction)\:*\s*(.+?)(?=Synonyms|$)', cloud_response, flags=re.DOTALL | re.IGNORECASE)
    #(?:\n[A-Z][a-zA-Z\s]*\:|\Z) — захватываем до: или до новой строки с новым заголовком (\n + заглавная буква + слово + :) или до конца строки (\Z).
    synonyms_pattern = re.findall(r'Synonyms\:*\n([\s\S]*?)(?=\Z)',cloud_response,flags=re.DOTALL | re.IGNORECASE)

    if not list_of_errors_pattern and not correct_translation:
        logging.error("❌ Claude вернул некорректный формат ответа!")
        return "❌ Ошибка: Не удалось обработать ответ от Claude."
    
    # Собираем результат в список
    result_list = ["📥 *Detailed grammar explanation*:\n", f"🟢*Original russian sentence*:\n{original_text}\n", f"🟣*User translation*:\n{user_translation}\n"]

    # Добавляем ошибки
    for line in list_of_errors_pattern:
        result_list.append(f"🔴*{line[0]} {line[1]}*: {line[2]}\n")

    # Добавляем корректный перевод
    for item in correct_translation:
        result_list.append(f"✅*{item[0]}*:\n➡️ {item[1]}\n")

    # Добавляем объяснения грамматики
    for k in grammar_explanation_pattern:
        result_list.append(f"🟡*{k[0]}*:")  # Добавляем заголовок
        grammar_parts = k[1].split("\n")  # Разбиваем текст по строкам
        for part in grammar_parts:
            clean_part = part.strip()
            if clean_part and clean_part not in ["-", ":"]:
                result_list.append(f"🔥{clean_part}")
    #result_list.append("\n")    

    # Добавляем альтернативные варианты
    for a in altern_sentence_pattern:
        result_list.append(f"\n🔵*{a[0]}*:\n {a[1].strip()}\n")  # Убираем лишние пробелы

    # Добавляем синонимы
    if synonyms_pattern:
        result_list.append("➡️ *Synonyms*:")
        #count = 0
        for s in synonyms_pattern:
            synonym_parts = s.split("\n")
            for part in synonym_parts:
                clean_part = part.strip()
                if not clean_part:
                    continue
                # if count > 0 and count % 2 == 0:
                #     result_list.append(f"{'-'*33}")
                result_list.append(f"🔄 {clean_part}")
                #count += 1

    # результат
    result_line_for_output = "\n".join(result_list)

    return result_line_for_output



async def log_translation_mistake(user_id, original_text, user_translation, categories, subcategories, score, correct_translation):
    global VALID_CATEGORIES, VALID_SUBCATEGORIES, VALID_CATEGORIES_lower, VALID_SUBCATEGORIES_lower
    #client = anthropic.Client(api_key=CLAUDE_API_KEY)

    # ✅ Логируем нормализованные значения
    if categories:
        print(f"🔎 LIST OF CATEGORIES FROM log_translation_function: {', '.join(categories)}")

    if subcategories:
        print(f"🔎 LIST OF SUBCATEGORIES log_translation_function: {', '.join(subcategories)}")


    # ✅ Перебираем все сочетания категорий и подкатегорий
    valid_combinations = []
    for cat in categories:
        cat_lower =cat.lower() # Приводим к нижнему регистру для соответствия VALID_SUBCATEGORIES
        for subcat in subcategories:
            subcat_lower = subcat.lower() # Приводим к нижнему регистру для соответствия VALID_SUBCATEGORIES
            if cat_lower in VALID_SUBCATEGORIES_lower and subcat_lower in VALID_SUBCATEGORIES_lower[cat_lower]:
                # ✅ Добавляем НОРМАЛИЗОВАННЫЕ значения для последующей обработки
                valid_combinations.append((cat_lower, subcat_lower))


    # ✅ Если есть хотя бы одно совпадение → логируем ВСЕ совпадения
    if valid_combinations:
        print(f"✅ Найдены следующие валидные комбинации ошибок выведенные в формате lower:")
        for main_category_lower, sub_category_lower in valid_combinations:
            print(f"➡️ {main_category_lower} - {sub_category_lower}")

    else:
        # ❗ Если не удалось классифицировать → помечаем как неклассифицированную ошибку
        print(f"⚠️ Ошибка классификации — помечаем как неклассифицированную.")
        valid_combinations.append(("Other mistake", "Unclassified mistake"))


    # ✅ Извлекаем уровень серьёзности ошибки (по умолчанию ставим 3)
    #severity = int(severity) if severity else 3

    # ✅ Проверка на идеальный перевод
    score = int(score) if score else 0


    # ✅ Если нет ошибок — не записываем в базу
    if len(valid_combinations) == 0:
        print(f"✅ Нет categories and subcategories соответствующих названию ошибок в базе данных — пропускаем запись в базу.")
        return

    # ✅ Убираем дубли из valid_combinations (чтобы не логировать одно и то же)
    valid_combinations = list(set(valid_combinations))


    # ✅ Логирование финальных данных для каждой комбинации
    for main_category, sub_category in valid_combinations:
        # ✅ Восстанавливаем оригинальные значения перед записью в базу данных
        main_category = next((cat for cat in VALID_CATEGORIES if cat.lower() == main_category), main_category)
        sub_category = next((subcat for subcat in VALID_SUBCATEGORIES.get(main_category, []) if subcat.lower() == sub_category), sub_category)
        
        if main_category == "Other mistake" and sub_category == "Unclassified mistake":
            print(f"⚠️ Ошибка '{main_category} - {sub_category}' добавлена в базу как неклассифицированная.")
        else:
            print(f"✅ Классифицировано: '{main_category} - {sub_category}'")

        print(f"🔍 Перед записью в БД: main_category = {main_category} | sub_category = {sub_category}")

        if not isinstance(user_id, int):
            print(f"❌ Ошибка типа данных: user_id = {type(user_id)}")
            return

        if not isinstance(main_category, str) or not isinstance(sub_category, str):
            print(f"❌ Ошибка типа данных: main_category = {type(main_category)}, sub_category = {type(sub_category)}")
            return


        # ✅ Запись в базу данных
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # ✅ Получаем id_for_mistake_table
                    cursor.execute("""
                    SELECT id_for_mistake_table 
                    FROM daily_sentences_deepseek
                    WHERE sentence=%s
                    LIMIT 1;
                """, (original_text, )
                    )
                    #sentence_id В нашем случае это идентификатор id_for_mistake_table Из таблицы daily_sentences_deepseek (для одинаковых предложений он одинаков) Для разных он разный.
                    # это нужно чтобы правильно Помечать предложения особенно одинаковые предложения и потом их правильно удалять из базы данных на основании этого идентификатора
                    result = cursor.fetchone()
                    sentence_id = result[0] if result else None

                    if sentence_id:
                        logging.info(f"✅ sentence_id для предложения '{original_text}': {sentence_id}")
                    else:
                        logging.warning(f"⚠️ sentence_id не найдено для предложения '{original_text}'")
                    
                    # ✅ Вставляем в таблицу ошибок с использованием общего идентификатора
                    cursor.execute("""
                        INSERT INTO detailed_mistakes_deepseek (
                            user_id, sentence, added_data, main_category, sub_category, mistake_count, sentence_id, correct_translation, score
                        ) VALUES (%s, %s, NOW(), %s, %s, 1, %s, %s, %s)
                        ON CONFLICT (user_id, sentence, main_category, sub_category)
                        DO UPDATE SET
                            mistake_count = detailed_mistakes_deepseek.mistake_count + 1,
                            attempt = detailed_mistakes_deepseek.attempt + 1,
                            last_seen = NOW(),
                            score = EXCLUDED.score;
                    """, (user_id, original_text, main_category, sub_category, sentence_id, correct_translation, score)
                    )
                    
                    conn.commit()
                    print(f"✅ Ошибка '{main_category} - {sub_category}' успешно записана в базу.")
                
                except Exception as e:
                    print(f"❌ Ошибка при записи в БД: {e}")
                    logging.error(f"❌ Ошибка при записи в БД: {e}")

    # ✅ Логирование успешного завершения обработки
    print(f"✅ Все ошибки успешно обработаны!")


async def check_user_translation(update: Update, context: CallbackContext, translation_text=None):
    
    if update.message is None or update.message.text is None:
        logging.warning("⚠️ update.message отсутствует в check_user_translation().")
        return
    
    if "pending_translations" in context.user_data and context.user_data["pending_translations"]:
        translation_text = "\n".join(context.user_data["pending_translations"])
        #context.user_data["pending_translations"] = []
    
    # Убираем команду "/translate", оставляя только переводы
    # message_text = update.message.text.strip()
    # translation_text = message_text.replace("/translate", "").strip()

    # Разбираем входной текст на номера предложений и переводы
    pattern = re.compile(r"(\d+)\.\s*([^\d\n]+(?:\n[^\d\n]+)*)", re.MULTILINE)
    translations = pattern.findall(translation_text)
    
    print(f"✅ Извлечено {len(translations)} переводов: {translations}")

    if not translations:
        msg_2 = await update.message.reply_text("❌ Ошибка: Формат перевода неверен. Должно быть: 1. <перевод>")
        add_service_msg_id(context, msg_2.message_id)
        return

    # Получаем ID пользователя
    user_id = update.message.from_user.id
    username = update.message.from_user.first_name

    # Подключаемся к базе данных
    conn = get_db_connection()
    cursor = conn.cursor()

    # Получаем разрешённые номера предложений
    cursor.execute("""
        SELECT unique_id FROM daily_sentences_deepseek WHERE date = CURRENT_DATE AND user_id = %s
    """, (user_id,))
    
    allowed_sentences = {row[0] for row in cursor.fetchall()}  # Собираем в set() для быстрого поиска

    # Проверяем каждое предложение
    results = []  # Храним результаты для Telegram

    for number_str, user_translation in translations:
        try:
            sentence_number = int(number_str)

            # Проверяем, принадлежит ли это предложение пользователю
            if sentence_number not in allowed_sentences:
                results.append(f"❌ Ошибка: Предложение {sentence_number} вам не принадлежит!")
                continue

            # Получаем оригинальный текст предложения
            cursor.execute("""
                SELECT id, sentence, session_id, id_for_mistake_table FROM daily_sentences_deepseek 
                WHERE date = CURRENT_DATE AND unique_id = %s AND user_id = %s;
            """, (sentence_number, user_id))

            row = cursor.fetchone()

            if not row:
                results.append(f"❌ Ошибка: Предложение {sentence_number} не найдено.")
                continue

            sentence_id, original_text, session_id, id_for_mistake_table  = row

            # Проверяем, отправлял ли этот пользователь перевод этого предложения
            cursor.execute("""
                SELECT id FROM translations_deepseek 
                WHERE user_id = %s AND sentence_id = %s AND timestamp::date = CURRENT_DATE;
            """, (user_id, sentence_id))

            existing_translation = cursor.fetchone()
            if existing_translation:
                results.append(f"⚠️ Вы уже переводили предложение {sentence_number}. Только первый перевод учитывается!")
                continue

            logging.info(f"📌 Проверяем перевод №{sentence_number}: {user_translation}")

            # Проверяем перевод через GPT
            MAX_FEEDBACK_LENGTH = 1000  # Ограничим длину комментария GPT

            try:
                feedback, categories, subcategories, score, correct_translation = await check_translation(original_text, user_translation, update, context, sentence_number)

            except Exception as e:
                print(f"⚠️ Ошибка при проверке перевода №{sentence_number}: {e}")
                logging.error(f"⚠️ Ошибка при проверке перевода №{sentence_number}: {e}", exc_info=True)
                feedback = "⚠️ Ошибка: не удалось проверить перевод."

            score = int(score) if score else 50

            # Обрезаем, если слишком длинный
            if len(feedback) > MAX_FEEDBACK_LENGTH:
                feedback = feedback[:MAX_FEEDBACK_LENGTH] + "...\n⚠️ Ответ GPT был сокращён."
            
            # ✅ Добавляем результат для последующей отправки    
            results.append(f"📜 **Предложение {sentence_number}**\n🎯 Оценка: {feedback}")

            # ✅ Сохраняем перевод в базу данных с защитой от ошибок
            cursor.execute("""
                INSERT INTO translations_deepseek (user_id, session_id, username, sentence_id, user_translation, score, feedback)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (user_id, session_id, username, sentence_id, user_translation, score, feedback))

            conn.commit()

            # Проверяем: реально ли это предложение есть в базе ошибок?
            cursor.execute("""
                SELECT COUNT(*) FROM detailed_mistakes_deepseek
                WHERE sentence_id = %s AND user_id = %s;
            """, (id_for_mistake_table, user_id))

            was_in_mistakes = cursor.fetchone()[0] > 0

            if score >= 85 and was_in_mistakes:
                try:
                    # # ✅ Проверяем, существует ли предложение с таким sentence_id
                    # cursor.execute("""
                    #     SELECT COUNT(*) FROM detailed_mistakes_deepseek
                    #     WHERE sentence_id = %s;
                    # """, (id_for_mistake_table, ))

                    # result = cursor.fetchone()
                    # if result and result[0] > 0:
                    logging.info(f"✅ Получаем все данные Предложения FROM detailed_mistakes_deepseek с sentence_id = {id_for_mistake_table}")
                    cursor.execute("""
                        SELECT user_id, score, attempt FROM detailed_mistakes_deepseek
                        WHERE sentence_id = %s;
                    """, (id_for_mistake_table,))
                        
                    rows = cursor.fetchall()
                    user_id = rows[0][0]
                    score_to_save = score
                    total_attempts = max(row[2] for row in rows)
                    # Добавляем 1 Чтобы учесть Текущую попытку (без добавления 1 Она не будет учтена)
                    total_attempts = total_attempts + 1
                    
                    logging.info(f"✅ Переносим данные Предложения FROM detailed_mistakes_deepseek в Таблицу successful_translations где находятся предложения с баллом 80 И более с sentence_id = {id_for_mistake_table}")
                    cursor.execute("""
                    INSERT INTO successful_translations (user_id, sentence_id, score, attempt, date)
                    VALUES (%s,%s,%s,%s, NOW());
                    """, (user_id, sentence_id, score_to_save, total_attempts))

                    logging.info(f"✅ Удаляем предложение с sentence_id = {id_for_mistake_table}, так как балл выше 85.")
                    
                    # ✅ Удаляем все ошибки, связанные с данным предложением
                    cursor.execute("""
                        DELETE FROM detailed_mistakes_deepseek
                        WHERE sentence_id = %s;
                        """, (id_for_mistake_table, ))
                    conn.commit()
                    logging.info(f"✅ Предложение с sentence_id = {id_for_mistake_table} успешно удалено.")

                except Exception as e:
                    logging.error(f"❌ Ошибка при удалении предложения с sentence_id = {id_for_mistake_table}: {e}")

            mistake_exists = was_in_mistakes

            if score >= 80 and not mistake_exists:
                cursor.execute("""
                    INSERT INTO successful_translations (user_id, sentence_id, score, attempt, date)
                    VALUES(%s, %s, %s, %s, NOW());
                    """, (user_id, sentence_id, score, int(1)))
                print(f"✅ Перевод на высоком уровне ({score}/100)")
                continue
            
            # ✅ Если оценка < 80 → только тогда сохраняем в базу
            try:
                await log_translation_mistake(user_id, original_text, user_translation, categories, subcategories, score, correct_translation)
            
            except Exception as e:
                print(f"⚠️ Ошибка при записи ошибки в detailed_mistakes_deepseek: {e}")

        except Exception as e:
            logging.error(f"❌ Ошибка обработки предложения {number_str}: {e}")
            
    cursor.close()
    conn.close()



async def get_original_sentences(user_id, context: CallbackContext):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
    
        # Выполняем SQL-запрос: выбираем 1 случайных предложений из базы данных в которую мы предварительно поместили предложение
        cursor.execute("SELECT sentence FROM sentences_deepseek ORDER BY RANDOM() LIMIT 1;")
        rows = [row[0] for row in cursor.fetchall()]   # Возвращаем список предложений
        print(f"📌 Найдено в базе данных: {rows}") # ✅ Логируем результат

        # ✅ Загружаем все предложения из базы ошибок
        cursor.execute("""
            SELECT sentence, sentence_id
            FROM detailed_mistakes_deepseek
            WHERE user_id = %s
            ORDER BY mistake_count DESC, last_seen ASC; 
        """, (user_id, ))
        
        # ✅ Используем set() для удаления дубликатов по sentence_id
        already_given_sentence_ids = set()
        unique_sentences = set()
        mistake_sentences = []

        for sentence, sentence_id in cursor.fetchall():
            if sentence_id and sentence_id not in already_given_sentence_ids:
                if sentence_id not in unique_sentences:
                    unique_sentences.add(sentence_id)
                    mistake_sentences.append(sentence)
                    already_given_sentence_ids.add(sentence_id)

                    # ✅ Ограничиваем до нужного количества предложений (например, 5)
                    if len(mistake_sentences) == 5:
                        break


        print(f"✅ Уникальные предложения из базы ошибок: {len(mistake_sentences)} / 5")

        # 🔹 3. Определяем, сколько предложений не хватает до 7
        num_sentences = 7 - len(rows) - len(mistake_sentences)

        print(f"📌 Найдено: {len(rows)} в базе данных + {len(mistake_sentences)} повторение ошибок. Генерируем ещё {num_sentences} предложений.")
        gpt_sentences = []
        
        # 📌 3. Остальные предложений генерируем через GPT
        if num_sentences > 0:
            print("⚠️ Генерируем дополнительные предложения через GPT-4...")
            gpt_sentences = await generate_sentences(user_id, num_sentences, context)
            #print(f"🚀 Сгенерированные GPT предложения: {gpt_sentences}") # ✅ Логируем результат
            
        
        # ✅ Проверяем финальный список предложений
        final_sentences = rows + mistake_sentences + gpt_sentences
        print(f"✅ Финальный список предложений: {final_sentences}")
        
        if not final_sentences:
            print("❌ Ошибка: Не удалось получить предложения!")
            return []  # Вернём пустой список в случае ошибки
        
        return final_sentences
    
    finally: # Закрываем курсор и соединение **в конце**, независимо от того, какая ветка выполнялась
        cursor.close()
        conn.close()



# Указываем ID нужных каналов
PREFERRED_CHANNELS = [
    "UCthmoIZKvuR1-KuwednkjHg",  # Deutsch mit Yehor
    "UCHLkEhIoBRu2JTqYJlqlgbw",  # Deutsch mit Rieke
    "UCeVQK7ZPXDOAyjY0NYqmX-Q", # Benjamin - Der Deutschlehrer
    "UCuVbK_d3wh3M8TYUk5aFCiQ",   # Lera
    "UCsxqCqZHE6guBCdSUEWpPsg",
    "UCm-E8MXdNquzETSsNxgoWig",
    "UCjdRXC3Wh2hDq8Utx7RIaMw",
    "UC9rwo-ES6aDKxD2qqkL6seA",
    "UCVx6RFaEAg46xfbsDjb440A",
    "UCvs8dBa7v3ti1QDaXE7dtKw",
    "UCE2vOZZIluHMtt2sAXhRhcw"
]

def search_youtube_videous(topic, max_results=5):
    query=topic
    if not YOUTUBE_API_KEY:
        print("❌ Ошибка: YOUTUBE_API_KEY не задан!")
        return []
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        
        # Поиск по приоритетным каналам
        video_data = []
        for channal_id in PREFERRED_CHANNELS:

            request = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=max_results,
                channelId=channal_id
            )
            response = request.execute()

            for item in response.get("items", []):
                title = item["snippet"]["title"]
                #title = title.replace('{', '{{').replace('}', '}}') # Экранирование фигурных скобок
                #title = title.replace('%', '%%') # Экранирование символов % 
                video_id = item["id"].get("videoId", "") # Безопасное извлечение videoId
                #video_url = f"https://www.youtube.com/watch?v={video_id}"
                if video_id:
                    video_data.append({'title': title, 'video_id': video_id})     

        # Если не найдено видео на приоритетных каналах, ищем по всем каналам
        if not video_data:
            print("❌ Видео на приоритетных каналах не найдено — ищем по всем каналам.")
            request = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=max_results,
                relevanceLanguage="de",
                regionCode="DE"
            )
            responce = request.execute()

            for item in responce.get("items", []):
                title = item["snippet"]["title"]
                #title = title.replace('{', '{{').replace('}', '}}') # Экранирование фигурных скобок
                #title = title.replace('%', '%%') # Экранирование символов % 
                video_id = item["id"].get("videoId", "") # Безопасное извлечение videoId
                #video_url = f"https://www.youtube.com/watch?v={video_id}"
                if video_id:
                    video_data.append({'title': title, 'video_id': video_id})
                                  
        if not video_data:
            return ["❌ Видео не найдено. Попробуйте позже."]
        
        # ✅ Теперь получаем количество просмотров для всех найденных видео
        video_ids =  ",".join([video['video_id'] for video in video_data if video['video_id']])
        if video_ids:
            stats_request = youtube.videos().list(
                part = "statistics",
                id=video_ids
            )
            stats_response = stats_request.execute()

            for item in stats_response.get("items", []):
                video_id = item["id"]
                view_count = int(item["statistics"].get("viewCount", 0))
                for video in video_data:
                    if video['video_id'] == video_id:
                        video["views"] = view_count

        # ✅ Подставляем значение по умолчанию (если данных о просмотрах нет)
        for video in video_data:
            video.setdefault("views", 0)

        # ✅ Сортируем по количеству просмотров (по убыванию)
        sorted_videos = sorted(video_data, key=lambda x: x["views"], reverse=True)

        # ✅ Возвращаем только 2 самых популярных видео
        top_videos = sorted_videos[:2]

        # ✅ Формируем ссылки в Telegram-формате
        preferred_videos = [
            f'<a href="{html.escape("https://www.youtube.com/watch?v=" + video["video_id"])}">▶️ {escape_html_with_bold(video["title"])}</a>'
            for video in top_videos
        ]

        print(f"preferred_videos after escape_html_with_bold: {preferred_videos}")
        return preferred_videos
    
    except Exception as e:
        print(f"❌ Ошибка при поиске видео в YouTube: {e}")
        return []


#📌 this function will filter and rate mistakes
async def rate_mistakes(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            
            # we calculate amount of translated sentences of the user in a week 
            cursor.execute("""
                SELECT COUNT(sentence_id) 
                FROM translations_deepseek 
                WHERE user_id = %s AND timestamp >= NOW() - INTERVAL '6 days'; 
            """, (user_id,))
            total_sentences = cursor.fetchone()
            total_sentences = total_sentences[0] if isinstance(total_sentences, tuple) else total_sentences or 0

            # ✅ 2. Select and calculate all mistakes KPI within a week
            cursor.execute("""
                WITH user_mistakes AS (
                    SELECT COUNT(*) AS mistakes_week
                    FROM detailed_mistakes_deepseek
                    WHERE user_id = %s
                    AND added_data >= NOW() - INTERVAL '6 days'
                ),
                top_category AS (
                    SELECT main_category
                    FROM detailed_mistakes_deepseek
                    WHERE user_id = %s
                    AND added_data >= NOW() - INTERVAL '6 days'
                    GROUP BY main_category
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ),
                number_of_topcategory_mist AS (
                    SELECT main_category, COUNT(*) AS number_of_top_category_mistakes
                    FROM detailed_mistakes_deepseek
                    WHERE user_id = %s
                    AND added_data >= NOW() - INTERVAL '6 days'
                    AND main_category = (SELECT main_category FROM top_category)
                    GROUP BY main_category
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                ),
                top_two_subcategories AS (
                    SELECT sub_category, 
                        COUNT(*) AS count,
                        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS subcategory_rank
                    FROM detailed_mistakes_deepseek 
                    WHERE user_id = %s
                    AND added_data >= NOW() - INTERVAL '6 days'
                    AND main_category = (SELECT main_category FROM top_category)
                    GROUP BY sub_category
                    ORDER BY COUNT(*) DESC
                    LIMIT 2
                )
                -- ✅ FINAL QUERY WITH LEFT JOIN TO AVOID EMPTY RESULTS
                SELECT 
                    COALESCE((SELECT mistakes_week FROM user_mistakes), 0) AS mistakes_week,
                    COALESCE(ntc.main_category, 'неизвестно') AS top_mistake_category,
                    COALESCE(ntc.number_of_top_category_mistakes, 0) AS number_of_top_category_mistakes,
                    COALESCE(MAX(CASE WHEN tts.subcategory_rank = 1 THEN tts.sub_category END), 'неизвестно') AS top_subcategory_1,
                    COALESCE(MAX(CASE WHEN tts.subcategory_rank = 2 THEN tts.sub_category END), 'неизвестно') AS top_subcategory_2
                FROM number_of_topcategory_mist ntc
                LEFT JOIN top_two_subcategories tts ON TRUE
                GROUP BY ntc.main_category, ntc.number_of_top_category_mistakes;
            """, (user_id, user_id, user_id, user_id))

            # ✅ ОБРАБАТЫВАЕМ СЛУЧАЙ, КОГДА ВОЗВРАЩАЕТСЯ МЕНЬШЕ ДАННЫХ
            result = cursor.fetchone()
            if result is not None:
                # Распаковываем все значения с защитой от отсутствия данных
                mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2 = result
            else:
                # Если нет данных — возвращаем пустые значения
                mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2 = 0, 'неизвестно', 0, 'неизвестно', 'неизвестно'


    return total_sentences, mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2


# ✅ Функция для проверки статуса ссылки
async def check_url(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    return True
                else:
                    print(f"⚠️ Ошибка ссылки {url} - Статус: {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Ошибка при проверке ссылки {url}: {e}")
        return False

# Полностью рабочая функция однако не получается экранировать чтобы оставить жирным текст в ** текст**.
# def escape_markdown_v2(text):
#     # Экранируем только спецсимволы Markdown
#     if not isinstance(text, str):
#         text = str(text)
#     escape_chars = r'_*[]()~`>#+-=|{}.,!:'
#     return ''.join(f'\\{char}' if char in escape_chars else char for char in text)

def escape_html_with_bold(text):
    if not isinstance(text, str):
        text = str(text)
    
    # Сначала заменим *text* на <b>text</b>
    bold_pattern = r'\*(.*?)\*'
    text = re.sub(bold_pattern, r'<b>\1</b>', text)
    
    # Теперь экранируем весь остальной текст кроме наших тэгов
    def escape_except_tags(part):
        if part.startswith('<b>') and part.endswith('</b>'):
            # Внутри <b>...</b> тоже нужно экранировать
            inner = html.escape(part[3:-4])
            return f"<b>{inner}</b>"
        else:
            return html.escape(part)
    
    # Разбиваем текст на куски: либо <b>...</b> либо обычный текст
    #re.split(r'(<b>.*?</b>)', text) работает так:
    #Разбивает текст вокруг кусков <b>...</b>,И сохраняет сами <b>...</b> в список благодаря скобкам () в регулярке.
    parts = re.split(r'(<b>.*?</b>)', text)
    escaped_parts = [escape_except_tags(part) for part in parts]
    return ''.join(escaped_parts)



# 📌📌📌📌📌
async def send_me_analytics_and_recommend_me(context: CallbackContext):
    #client = openai.AsyncOpenAI(api_key=openai.api_key)
    task_name = f"send_me_analytics_and_recommend_me"
    system_instruction = f"send_me_analytics_and_recommend_me"
    assistant_id, _ = get_or_create_openai_resources(system_instruction, task_name)
            

    #get all user_id's from _DB to itterate over them and send them recommendations
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            SELECT DISTINCT user_id FROM detailed_mistakes_deepseek;
            """)
            user_ids = cursor.fetchall()
    if not user_ids:
        print("❌ Нет пользователей с ошибками за последнюю неделю.")
        return

    for user_id, in user_ids:
        total_sentences, mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2 = await rate_mistakes(user_id)
        if total_sentences:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT username FROM translations_deepseek WHERE user_id = %s;""",
                        (user_id, ))

                    result = cursor.fetchone()
                    username = result[0] if result else "Unknown User"

                # ✅ Создаём новый thread каждый раз
                thread = client.beta.threads.create()
                thread_id = thread.id

            # ✅ Запрашиваем тему у OpenAI
            user_message = f"""
            - **Категория ошибки:** {top_mistake_category}  
            - **Первая подкатегория:** {top_mistake_subcategory_1}  
            - **Вторая подкатегория:** {top_mistake_subcategory_2}  
            """

            for attempt in range(5):
                try:
                    client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_message
                )

                    run = client.beta.threads.runs.create(
                        thread_id=thread_id,
                        assistant_id=assistant_id
                    )
                    while True:
                        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                        if run_status.status == "completed":
                            break
                        await asyncio.sleep(1)  # подожди чуть-чуть

                    # Получаем сообщения после завершения run
                    messages = client.beta.threads.messages.list(thread_id=thread_id)
                    last_message = messages.data[0]  # обычно последнее — ответ
                    topic = last_message.content[0].text.value

                    # response = await client.chat.completions.create(
                    # model="gpt-4-turbo",
                    # messages=[{"role": "user", "content": prompt}]
                    # )
                    # topic = response.choices[0].message.content.strip()
                    
                    try:
                        client.beta.threads.delete(thread_id=thread_id)
                        logging.info(f"🗑️ Thread удалён: {thread_id}")

                    except Exception as e:
                        logging.warning(f"Не удалось удалить thread: {e}")

                    print(f"📌 Определена тема: {topic}")
                    break
                except openai.RateLimitError:
                    wait_time = (attempt + 1 )*5
                    print(f"⚠️ OpenAI API перегружен. Ждём {wait_time} сек...")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    print(f"⚠️ Ошибка OpenAI: {e}")
                    continue
                
            # ✅ Ищем видео на YouTube только по конкретным каналам
            video_data = search_youtube_videous(topic)

            # ✅ Добавляем логирование для диагностики
            if not isinstance(video_data, list):
                print(f"❌ ОШИБКА: search_youtube_videous вернула {type(video_data)} вместо списка!")
            if not video_data:
                print("❌ Видео не найдено. Список пуст.")
            else:
                print(f"✅ Найдено {len(video_data)} видео:")
                for video in video_data:
                    print(f"▶️ {video}")
            
            # ✅ Формируем список ссылок только если элемент является словарём
            # ✅ Нет необходимости преобразовывать снова — список уже готов
            valid_links = video_data

            
            if not valid_links:
                valid_links = ["❌ Не удалось найти видео на YouTube по этой теме. Попробуйте позже."]

            rounded_value = round(mistakes_week/total_sentences, 2)
            # ✅ Формируем сообщение для пользователя
            recommendations = (
                f"🧔 *{username}*,\nВы *перевели* за неделю: {total_sentences} предложений;\n"
                f"📌 *В них допущено* {mistakes_week} ошибок;\n"
                f"🚨 *Количество ошибок на одно предложение:* {rounded_value} штук;\n"
                f"🔴 *Больше всего ошибок:* {number_of_top_category_mistakes} штук в категории:\n {top_mistake_category or 'неизвестно'}\n"
            )
            if top_mistake_subcategory_1:
                recommendations += (f"📜 *Основные ошибки в подкатегории:*\n {top_mistake_subcategory_1}\n\n")
            if top_mistake_subcategory_2:
                recommendations += (f"📜 *Вторые по частоте ошибки в подкатегории:*\n {top_mistake_subcategory_2}\n\n")
            
            # ✅ Добавляем строку с рекомендацией → ЭТО ВАЖНО!
            recommendations += (f"🟢 *Рекомендую посмотреть:*\n\n")
            recommendations = escape_html_with_bold(recommendations)


            # ✅ Добавляем рабочие ссылки
            recommendations += "\n\n".join(valid_links)
            
            #Debugging...
            print("DEBUG: ", recommendations)


            # ✅ Отправляем сообщение пользователю
            await context.bot.send_message(
                chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, 
                text=recommendations,
                parse_mode = "HTML"
                )
            await asyncio.sleep(5)

        else:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT username FROM translations_deepseek WHERE user_id = %s;
                    """, (user_id, ))
                    result = cursor.fetchone()
                    username = result[0] if result else f"User {user_id}"
            
            await context.bot.send_message(
                chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
                text=escape_html_with_bold(f"⚠️ Пользователь {username} не перевёл ни одного предложения на этой неделе."),
                parse_mode="HTML"
            )


async def force_finalize_sessions(context: CallbackContext = None):
    """Завершает ВСЕ незавершённые сессии только за сегодняшний день в 23:59."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE user_progress_deepseek 
        SET end_time = NOW(), completed = TRUE
        WHERE completed = FALSE AND start_time::date = CURRENT_DATE;
    """)

    conn.commit()
    cursor.close()
    conn.close()

    msg = await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="🔔 Все незавершённые сессии за сегодня автоматически закрыты!")
    #add_service_msg_id(context, msg.message_id)



#SQL Запрос проверено
async def send_weekly_summary(context: CallbackContext):

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Собираем статистику за неделю
    cursor.execute("""
        SELECT 
        t.username, 
        COUNT(DISTINCT t.sentence_id) AS всего_переводов,
        COALESCE(AVG(t.score), 0) AS средняя_оценка,
        COALESCE(p.avg_time, 0) AS среднее_время_сессии_в_минутах, -- ✅ Среднее время сессии
        COALESCE(p.total_time, 0) AS общее_время_в_минутах, -- ✅ Теперь есть и общее время
        (SELECT COUNT(*) 
        FROM daily_sentences_deepseek 
        WHERE date >= CURRENT_DATE - INTERVAL '6 days' 
        AND user_id = t.user_id) 
        - COUNT(DISTINCT t.sentence_id) AS пропущено_за_неделю,
        COALESCE(AVG(t.score), 0) 
            - (COALESCE(p.avg_time, 0) * 2) -- ✅ Среднее время в штрафе
            - ((SELECT COUNT(*) 
                FROM daily_sentences_deepseek 
                WHERE date >= CURRENT_DATE - INTERVAL '6 days' 
                AND user_id = t.user_id) 
            - COUNT(DISTINCT t.sentence_id)) * 20
            AS итоговый_балл
    FROM translations_deepseek t
    LEFT JOIN (
        SELECT user_id, 
            AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time, -- ✅ Среднее время сессии
            SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time -- ✅ Общее время
        FROM user_progress_deepseek 
        WHERE completed = TRUE 
        AND start_time >= CURRENT_DATE - INTERVAL '6 days'
        GROUP BY user_id
    ) p ON t.user_id = p.user_id
    WHERE t.timestamp >= CURRENT_DATE - INTERVAL '6 days'
    GROUP BY t.username, t.user_id, p.avg_time, p.total_time
    ORDER BY итоговый_балл DESC;

    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="📊 Неделя прошла, но никто не перевел ни одного предложения!")
        return

    summary = "🏆 Итоги недели:\n\n"

    medals = ["🥇", "🥈", "🥉"]
    for i, (username, count, avg_score, avg_minutes, total_minutes, missed, final_score) in enumerate(rows):
        medal = medals[i] if i < len(medals) else "💩"
        summary += (
            f"{medal} {username}\n"
            f"📜 Переведено: {count}\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общее: {total_minutes:.1f} мин\n"
            f"🚨 Пропущено: {missed}\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )

    await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text=summary)



async def user_stats(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.first_name

    conn = get_db_connection()
    cursor = conn.cursor()

    # 📌 Статистика за сегодняшний день (обновлено для среднего времени) Если за семь дней считать то нужно так: WHERE date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE - INTERVAL '1 day'
    cursor.execute("""
        SELECT 
            COUNT(DISTINCT t.sentence_id) AS переведено,  
            COALESCE(AVG(t.score), 0) AS средняя_оценка,
            COALESCE((
                SELECT AVG(EXTRACT(EPOCH FROM (p.end_time - p.start_time)) / 60)  -- ✅ Используем AVG вместо SUM
                FROM user_progress_deepseek p
                WHERE p.user_id = t.user_id 
                    AND p.start_time::date = CURRENT_DATE
                    AND p.completed = TRUE
            ), 0) AS среднее_время_сессии_в_минутах,  -- ✅ Обновили название, чтобы было понятно
            GREATEST(0, (SELECT COUNT(*) FROM daily_sentences_deepseek 
                        WHERE date = CURRENT_DATE AND user_id = t.user_id) - COUNT(DISTINCT t.sentence_id)) AS пропущено,
            COALESCE(AVG(t.score), 0) 
                - (COALESCE((
                    SELECT AVG(EXTRACT(EPOCH FROM (p.end_time - p.start_time)) / 60)  -- ✅ Здесь тоже AVG
                    FROM user_progress_deepseek p
                    WHERE p.user_id = t.user_id 
                        AND p.start_time::date = CURRENT_DATE
                        AND p.completed = TRUE
                ), 0) * 2) 
                - (GREATEST(0, (SELECT COUNT(*) FROM daily_sentences_deepseek
                                WHERE date = CURRENT_DATE AND user_id = t.user_id) - COUNT(DISTINCT t.sentence_id)) * 20) AS итоговый_балл
        FROM translations_deepseek t
        WHERE t.user_id = %s AND t.timestamp::date = CURRENT_DATE
        GROUP BY t.user_id;
    """, (user_id,))

    today_stats = cursor.fetchone()

    # 📌 Недельная статистика (обновлено для среднего времени)
    cursor.execute("""
        SELECT 
            t.user_id,
            COUNT(DISTINCT t.sentence_id) AS всего_переводов,
            COALESCE(AVG(t.score), 0) AS средняя_оценка,
            COALESCE(p.avg_session_time, 0) AS среднее_время_сессии_в_минутах,  
            COALESCE(p.total_time, 0) AS общее_время_за_неделю,  
            GREATEST(0, COALESCE(ds.total_sentences, 0) - COUNT(DISTINCT t.sentence_id)) AS пропущено_за_неделю,
            COALESCE(AVG(t.score), 0) 
                - (COALESCE(p.avg_session_time, 0) * 2)  
                - (GREATEST(0, COALESCE(ds.total_sentences, 0) - COUNT(DISTINCT t.sentence_id)) * 20) AS итоговый_балл
        FROM translations_deepseek t
        LEFT JOIN (
            -- ✅ Отдельный подзапрос для корректного расчёта времени по каждому пользователю
            SELECT 
                user_id, 
                AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60) AS avg_session_time, 
                SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60) AS total_time 
            FROM user_progress_deepseek
            WHERE completed = TRUE 
                AND start_time >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY user_id
        ) p ON t.user_id = p.user_id
        LEFT JOIN (
            SELECT user_id, COUNT(*) AS total_sentences
            FROM daily_sentences_deepseek
            WHERE date >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY user_id
        ) ds ON t.user_id = ds.user_id
        WHERE t.timestamp >= CURRENT_DATE - INTERVAL '6 days' 
            AND t.user_id = %s  -- ✅ Фильтр по конкретному пользователю
        GROUP BY t.user_id, p.avg_session_time, p.total_time, ds.total_sentences;
    """, (user_id,))

    weekly_stats = cursor.fetchone()

    cursor.close()
    conn.close()

    # 📌 Формирование ответа
    if today_stats:
        today_text = (
            f"📅 Сегодняшняя статистика ({username})\n"
            f"🔹 Переведено: {today_stats[0]}\n"
            f"🎯 Средняя оценка: {today_stats[1]:.1f}/100\n"
            f"⏱ Среднее время сессии: {today_stats[2]:.1f} мин\n"
            f"🚨 Пропущено: {today_stats[3]}\n"
            f"🏆 Итоговый балл: {today_stats[4]:.1f}\n"
        )
    else:
        today_text = f"📅 **Сегодняшняя статистика ({username})**\n❌ Нет данных (вы ещё не переводили)."

    if weekly_stats:
        weekly_text = (
            f"\n📆 Статистика за неделю\n"
            f"🔹 Переведено: {weekly_stats[1]}\n"
            f"🎯 Средняя оценка: {weekly_stats[2]:.1f}/100\n"
            f"⏱ Среднее время сессии: {weekly_stats[3]:.1f} мин\n"
            f"⏱ Общее время за неделю: {weekly_stats[4]:.1f} мин\n"
            f"🚨 Пропущено за неделю: {weekly_stats[5]}\n"
            f"🏆 Итоговый балл: {weekly_stats[6]:.1f}\n"
        )
    else:
        weekly_text = "\n📆 **Статистика за неделю**\n❌ Нет данных."

    await update.message.reply_text(today_text + weekly_text)



async def send_daily_summary(context: CallbackContext):

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Собираем активных пользователей (кто перевёл хотя бы одно предложение)
    cursor.execute("""
        SELECT DISTINCT user_id, username 
        FROM translations_deepseek
        WHERE timestamp::date = CURRENT_DATE;
    """)
    active_users = {row[0]: row[1] for row in cursor.fetchall()}

    # 🔹 Собираем всех, кто хоть что-то писал в чат
    cursor.execute("""
        SELECT DISTINCT user_id, username
        FROM messages_deepseek
        WHERE timestamp >= date_trunc('month', CURRENT_DATE);
    """)
    all_users = {row[0]: row[1] for row in cursor.fetchall()}
    for user_id, username in all_users.items():
        print(f"User ID from rows: {user_id}, uswername: {username}")

    # 🔹 Собираем статистику за день
    cursor.execute("""
       SELECT 
            ds.user_id, 
            COUNT(DISTINCT ds.id) AS total_sentences,
            COUNT(DISTINCT t.id) AS translated,
            (COUNT(DISTINCT ds.id) - COUNT(DISTINCT t.id)) AS missed,
            COALESCE(p.avg_time, 0) AS avg_time_minutes, 
            COALESCE(p.total_time, 0) AS total_time_minutes, 
            COALESCE(AVG(t.score), 0) AS avg_score,
            COALESCE(AVG(t.score), 0) 
            - (COALESCE(p.avg_time, 0) * 2) 
            - ((COUNT(DISTINCT ds.id) - COUNT(DISTINCT t.id)) * 20) AS final_score
        FROM daily_sentences_deepseek ds
        LEFT JOIN translations_deepseek t ON ds.user_id = t.user_id AND ds.id = t.sentence_id
        LEFT JOIN (
            SELECT user_id, 
                AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time, 
                SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time
            FROM user_progress_deepseek
            WHERE completed = true
        		AND start_time::date = CURRENT_DATE -- ✅ Теперь только за день
            GROUP BY user_id
        ) p ON ds.user_id = p.user_id
        WHERE ds.date = CURRENT_DATE
        GROUP BY ds.user_id, p.avg_time, p.total_time
        ORDER BY final_score DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # 🔹 Формируем итоговый отчёт
    if not rows:
        await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="📊 Сегодня никто не перевёл ни одного предложения!")
        return

    summary = "📊 Итоги дня:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, total_sentences, translated, missed, avg_minutes, total_time_minutes, avg_score, final_score) in enumerate(rows):
        username = all_users.get(int(user_id), 'Неизвестный пользователь')  # ✅ Берём имя пользователя из словаря
        medal = medals[i] if i < len(medals) else "💩"
        summary += (
            f"{medal} {username}\n"
            f"📜 Всего предложений: {total_sentences}\n"
            f"✅ Переведено: {translated}\n"
            f"🚨 Не переведено: {missed}\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общее: {total_time_minutes:.1f} мин\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )


    # 🚨 **Добавляем блок про ленивых**
    lazy_users = {uid: uname for uid, uname in all_users.items() if uid not in active_users}
    if lazy_users:
        summary += "\n🦥 Ленивцы (писали в чат, но не переводили):\n"
        for username in lazy_users.values():
            summary += f"👤 {username}: ничего не перевёл!\n"

    await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text=summary)



async def send_progress_report(context: CallbackContext):
    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Получаем всех пользователей, которые писали в чат **за месяц**
    cursor.execute("""
        SELECT DISTINCT user_id, username 
        FROM messages_deepseek
        WHERE timestamp >= date_trunc('month', CURRENT_DATE);
    """)
    all_users = {int(row[0]): row[1] for row in cursor.fetchall()}

    # 🔹 Получаем всех, кто перевёл хотя бы одно предложение **за сегодня**
    cursor.execute("""
        SELECT DISTINCT user_id FROM translations_deepseek WHERE timestamp::date = CURRENT_DATE;
    """)
    active_users = {row[0] for row in cursor.fetchall()}

    # 🔹 Собираем статистику по пользователям **за сегодня**(checked)
    cursor.execute("""
        SELECT 
        ds.user_id,
        COUNT(DISTINCT ds.id) AS всего_предложений,
        COUNT(DISTINCT t.id) AS переведено,
        (COUNT(DISTINCT ds.id) - COUNT(DISTINCT t.id)) AS пропущено,
        COALESCE(p.avg_time, 0) AS среднее_время_сессии_в_минутах, -- ✅ Среднее время за день
        COALESCE(p.total_time, 0) AS общее_время_за_день, -- ✅ Общее время за день
        COALESCE(AVG(t.score), 0) AS средняя_оценка,
        COALESCE(AVG(t.score), 0) 
            - (COALESCE(p.avg_time, 0) * 2) -- ✅ Используем среднее время в расчётах
            - ((COUNT(DISTINCT ds.id) - COUNT(DISTINCT t.id)) * 20) AS итоговый_балл
    FROM daily_sentences_deepseek ds
    LEFT JOIN translations_deepseek t ON ds.user_id = t.user_id AND ds.id = t.sentence_id
    LEFT JOIN (
        SELECT user_id, 
            AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time, -- ✅ Среднее время сессии за день
            SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time -- ✅ Общее время за день
        FROM user_progress_deepseek
        WHERE completed = TRUE 
            AND start_time::date = CURRENT_DATE -- ✅ Теперь только за день
        GROUP BY user_id
    ) p ON ds.user_id = p.user_id
    WHERE ds.date = CURRENT_DATE
    GROUP BY ds.user_id, p.avg_time, p.total_time
    ORDER BY итоговый_балл DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # 🔹 Формируем отчёт
    if not rows:
        await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="📊 Сегодня никто не перевёл ни одного предложения!")
        return
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    progress_report = f"📊 Промежуточные итоги перевода:\n🕒 Время отчёта:\n{current_time}\n\n"

    for user_id, total, translated, missed, avg_minutes, total_minutes, avg_score, final_score in rows:
        progress_report += (
            f"👤 {all_users.get(int(user_id), 'Неизвестный пользователь')}\n"
            f"📜 Переведено: {translated}/{total}\n"
            f"🚨 Не переведено: {missed}\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общ.: {total_minutes:.1f} мин\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )

    # 🚨 **Добавляем блок про ленивых (учитываем всех, кто писал в чат за месяц)**
    lazy_users = {uid: uname for uid, uname in all_users.items() if uid not in active_users}
    if lazy_users:
        progress_report += "\n🦥 Ленивцы (писали в чат, но не переводили):\n"
        for username in lazy_users.values():
            progress_report += f"👤 {username}: ничего не перевёл!\n"

    await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text=progress_report)


async def error_handler(update, context):
    logging.error(f"❌ Ошибка в обработчике Telegram: {context.error}")


# Глобальная переменная
GOOGLE_CREDS_FILE_PATH = None

# ✅ # ✅ Загружаем переменные окружения из .env-файла (только при локальной разработке)
# Это загрузит все переменные из file with name .env which was created by me в os.environ

def prepare_google_creds_file():
    global GOOGLE_CREDS_FILE_PATH
    global success
    print("✅ .env loaded?", success)
    print("🧪 Функция prepare_google_creds_file вызвана")

    # ✅ 1. Попробовать использовать путь к локальному .json-файлу
    direct_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    print(f"📢 direct_path (print): {direct_path}")
    logging.info(f"direct_path: {direct_path}")

    if direct_path:
        print("🌐 Переменная найдена:", direct_path)
        print("🧱 Существует ли файл?", Path(direct_path).exists())
        GOOGLE_CREDS_FILE_PATH = direct_path
        return GOOGLE_CREDS_FILE_PATH
    
    # ✅ 2. Попробовать использовать GOOGLE_CREDS_JSON (из Railway)
    if GOOGLE_CREDS_FILE_PATH and Path(GOOGLE_CREDS_FILE_PATH).exists():
        return GOOGLE_CREDS_FILE_PATH
    
    raw_creds = os.getenv("GOOGLE_CREDS_JSON")
    if not raw_creds:
        raise RuntimeError("❌ Не найдены переменные GOOGLE_APPLICATION_CREDENTIALS или GOOGLE_CREDS_JSON.")

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".json") as temp_key_file:
        temp_key_file.write(raw_creds)
        temp_key_file.flush()
        # Когда создаё временный файл через tempfile.NamedTemporaryFile, Python возвращает объект этого файла. 
        # У него есть атрибут .name, который содержит полный путь к этому файлу в файловой системе
        GOOGLE_CREDS_FILE_PATH = temp_key_file.name
        print(f"🧪 Сгенерирован временный ключ: {GOOGLE_CREDS_FILE_PATH}")

    return GOOGLE_CREDS_FILE_PATH



async def mistakes_to_voice(username, sentence_pairs):
    #global GOOGLE_CREDS_FILE_PATH
    key_path = prepare_google_creds_file()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path

    client = texttospeech.TextToSpeechClient()

    audio_segments = []

    def synthesize(text, language_code, voice_name):
        input_data = texttospeech.SynthesisInput(text = text)

        voice = texttospeech.VoiceSelectionParams(
            language_code = language_code, name=voice_name
        )

        config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.9 # 90% скорости
        )

        response = client.synthesize_speech(
            input=input_data, voice=voice, audio_config=config 
        )

        return AudioSegment.from_file_using_temporary_files(io.BytesIO(response.audio_content))

    for russian, german in sentence_pairs:
        print(f"🎤 Синтезируем: {russian} -> {german}")
        # Русский (один раз)
        ru_audio = synthesize(russian, "ru-RU", "ru-RU-Wavenet-C")
        # Немецкий (дважды)
        de_audio_1 = synthesize(german, "de-DE", "de-DE-Wavenet-B")
        de_audio_2 = synthesize(german, "de-DE", "de-DE-Wavenet-B")

        # Объединяем
        combined = ru_audio + de_audio_1 + de_audio_2
        audio_segments.append(combined)

    final_audio = sum(audio_segments)

    output_path = f"{username}.mp3"

    final_audio.export(output_path, format="mp3")
    print(f"🔊 Сохранён итоговый файл: {output_path}")


async def get_yesterdays_mistakes_for_audio_message(context: CallbackContext):
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:

            # take all users who made at least one mistake from detailed_mistakes_deepseek table
            cursor.execute("""
                SELECT DISTINCT user_id FROM detailed_mistakes_deepseek
                WHERE added_data >= NOW() - INTERVAL '6 days';
            """)
            user_ids = [i[0] for i in cursor.fetchall() if i[0] is not None]
            print(user_ids)
            for user_id in user_ids:
                original_by_id = {}

                cursor.execute("""
                SELECT username FROM user_progress_deepseek
                WHERE user_id = %s;
                """, (user_id,))
                row = cursor.fetchone()
                username = row[0] if row and row[0] else f"useer_{user_id}"

                ## Шаг 1 — Собираем оригинальные предложения по user_id
                # ✅ Загружаем все предложения из базы ошибок
                cursor.execute("""
                    SELECT sentence, correct_translation
                    FROM detailed_mistakes_deepseek
                    WHERE user_id = %s
                    ORDER BY mistake_count DESC, last_seen ASC; 
                """, (user_id, ))
                
                # ✅ Используем set() для удаления дубликатов по sentence_id
                already_given_sentence_translation = set()
                unique_sentences = set()
                mistake_sentences = []
                result_for_audio = []
                
                rows = cursor.fetchall()
                max_to_collect = min(len(rows), 5)

                for sentence, correct_translation in rows:
                    if sentence and correct_translation and correct_translation not in already_given_sentence_translation and sentence not in mistake_sentences:
                        if correct_translation not in unique_sentences:
                            unique_sentences.add(correct_translation)
                            mistake_sentences.append(sentence)
                            already_given_sentence_translation.add(correct_translation)
                            original_by_id[correct_translation] = sentence

                            # ✅ Ограничиваем до нужного количества предложений (например, 5)
                            
                            if len(mistake_sentences) == max_to_collect:
                                break

                sentence_pairs = [(origin_sentence, correct_transl) for correct_transl, origin_sentence in original_by_id.items()]
                try:
                    await mistakes_to_voice(username, sentence_pairs)
                except Exception as e:
                    print(f"❌ Ошибка синтеза речи для {username}: {e}")
                    continue
                audio_path = Path(f"{username}.mp3")
                print(f"📦 Размер файла: {audio_path.stat().st_size / 1024 / 1024:.2f} MB ")

                if audio_path.exists():
                    try:
                        start = asyncio.get_running_loop().time()
                        with audio_path.open("rb") as audio_file:
                            await context.bot.send_audio(
                                chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, 
                                audio=audio_file,
                                caption=f"🎧 Ошибки пользователя @{username} за вчерашний день."
                            )
                        print(f"⏱ Отправка заняла {asyncio.get_running_loop().time() - start:.2f} секунд")
                        await asyncio.sleep(5)
                    except Exception as e:
                        print(f"❌ Ошибка при отправке аудиофайла для @{username}: {e}")

                    try:    
                        audio_path.unlink()
                    except FileNotFoundError:
                        print(f"⚠️ Файл уже был удалён: {audio_path}")
                
                else:
                    await context.bot.send_message(
                        chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
                        text=f"❌ Для пользователя @{username} не найден аудиофайл."
                    )
                    await asyncio.sleep(5)


# import atexit

# def cleanup_creds_file():
#     global GOOGLE_CREDS_FILE_PATH
#     if GOOGLE_CREDS_FILE_PATH and os.path.exists(GOOGLE_CREDS_FILE_PATH):
#         os.remove(GOOGLE_CREDS_FILE_PATH)
#         print(f"🧹 Удалён временный ключ: {GOOGLE_CREDS_FILE_PATH}")

# atexit.register(cleanup_creds_file)




def main():
    global application

    #defaults = Defaults(timeout=60)  # увеличили таймаут до 60 секунд
    application = Application.builder().token(TELEGRAM_DeepSeek_BOT_TOKEN).build()
    application.bot.request.timeout = 60

    # 🔹 Добавляем обработчики команд (исправленный порядок)
    application.add_handler(CommandHandler("start", start))
    # 🔥 Логирование всех сообщений (группа -1, не блокирует цепочку)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_message, block=False), group=-1)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message, block=False), group=1)  # ✅ Сохраняем переводы
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_click, block=False), group=1)  # ✅ Обрабатываем кнопки 
    application.add_handler(CallbackQueryHandler(handle_explain_request, pattern=r"^explain:"))

    application.add_handler(CommandHandler("translate", check_user_translation))  # ✅ Проверка переводов
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_translation_from_text, block=False), group=1)  # ✅ Проверяем переводы


    application.add_handler(CallbackQueryHandler(topic_selected)) #Он ждет любые нажатия на inline-кнопки.
    application.add_handler(MessageHandler(filters.TEXT, log_all_messages, block=False), group=2)  # 👈 Добавляем в main()

    application.add_error_handler(error_handler)

    scheduler = BackgroundScheduler()

    def run_async_job(async_func, context=None):
         if context is None:
             context = CallbackContext(application=application)   # Создаем `context`, если его нет

         try:
             loop = asyncio.get_running_loop() # ✅ Берем уже работающий event loop
         except RuntimeError:
             loop = asyncio.new_event_loop()  # ❌ В потоке `apscheduler` нет loop — создаем новый
             asyncio.set_event_loop(loop)
         loop.run_until_complete(async_func(context)) # ✅ Теперь event loop всегда работает

    # ✅ Добавляем задачу в `scheduler` ДЛЯ УТРА
    print("📌 Добавляем задачу в scheduler...")
    scheduler.add_job(lambda: run_async_job(send_morning_reminder,CallbackContext(application=application)),"cron", hour=5, minute=5)
    scheduler.add_job(lambda: run_async_job(send_morning_reminder,CallbackContext(application=application)),"cron", hour=15, minute=30)

    scheduler.add_job(
        lambda: run_async_job(send_german_news, CallbackContext(application=application)), 
        "cron",
        hour=4,
        minute=1,
        #day_of_week = "mon,tue,thu,fri,sat"
        day_of_week = "mon,fri"
    )
    
    scheduler.add_job(lambda: run_async_job(send_me_analytics_and_recommend_me, CallbackContext(application=application)), "cron", day_of_week="fri", hour=15, minute=15)
    scheduler.add_job(lambda: run_async_job(send_me_analytics_and_recommend_me, CallbackContext(application=application)), "cron", day_of_week="mon", hour=6, minute=5) 
    #scheduler.add_job(lambda: run_async_job(send_me_analytics_and_recommend_me, CallbackContext(application=application)), "cron", day_of_week="sun", hour=7, minute=7)
    
    scheduler.add_job(lambda: run_async_job(force_finalize_sessions, CallbackContext(application=application)), "cron", hour=21, minute=59)
    
    scheduler.add_job(lambda: run_async_job(send_daily_summary), "cron", hour=20, minute=52)
    scheduler.add_job(lambda: run_async_job(send_weekly_summary), "cron", day_of_week="sun", hour=20, minute=55)

    for hour in [7,12,16]:
        scheduler.add_job(lambda: run_async_job(send_progress_report), "cron", hour=hour, minute=5)

    scheduler.add_job(lambda: run_async_job(get_yesterdays_mistakes_for_audio_message, CallbackContext(application=application)), "cron", hour=5, minute=15)

    scheduler.start()
    print("🚀 Бот запущен! Ожидаем сообщения...")
    application.run_polling()






if __name__ == "__main__":
    main()