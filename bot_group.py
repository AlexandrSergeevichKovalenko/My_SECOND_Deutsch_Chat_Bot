# To fix this, you need to get the `message_thread_id` from the `update.message` when the user sends `/start` *within a topic* and pass it to `context.bot.send_message`.

# Additionally, your initial comment `# не получилось доделать чтобы в отдельные группы отправлялось информация` suggests you might want the scheduled messages (like news, summaries) to go into specific topic threads as well, rather than the main "General" thread. Your `TOPICS_TELEGRAM` dictionary already defines IDs for these topics. We can use these IDs in the scheduled job functions.

# Finally, the handlers in `main()` seem to have a redundant `MessageHandler` for `handle_button_click` and a call inside `handle_user_message` that should be removed or fixed. The text buttons on `ReplyKeyboardMarkup` are processed as regular text messages, not callback queries.

# Here's the refined code with the necessary fixes:

# 1.  **Modify `start` function:** Pass `message_thread_id` to `send_message`.
# 2.  **Modify Scheduled Functions:** Send messages to the specific `thread_id` defined in `TOPICS_TELEGRAM`.
# 3.  **Modify Interactive Functions (`choose_topic`, `letsgo`, `done`, `user_stats`, `check_translation_from_text`):** Ensure they correctly get `chat_id` and `message_thread_id` from *either* `update.message` (for Reply button clicks / commands) or `update.callback_query` (for Inline button clicks) at the start of the function. (Your current functions already seem mostly prepared for this).
# 4.  **Add `MessageHandler`s for Reply Keyboard Button Text:** Register specific handlers for the text strings of the buttons in `MAIN_MENU`.
# 5.  **Clean up `main()`:** Remove the redundant `MessageHandler` registration.
# 6.  **Clean up `handle_user_message`:** Remove the incorrect call to `handle_button_click`.



# не получилось доделать чтобы в отдельные группы отправлялось информация
# Этот бот может работать с DEEPSEEK
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

# Настраиваем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

#MessageHandler → ожидает update.message.
#CallbackQueryHandler → ожидает update.callback_query.

application = None
scheduler = None

TOPICS_TELEGRAM = {
    "General": {
        "id": None,  # Это сам чат. Получено сообщение в чате-1002258968332, threat_id: None
        "allowed_buttons": []  # Можем использовать Просто для переписки
    },
    "Empfehlungen": {
        "id": 3560,
        "allowed_buttons": [] # сюда будут приходить рекомендации
    },
    "Wöchenliche Statistik": {
        "id": 3495,
        "allowed_buttons": [] # сюда приходит по расписанию статистика
    },
        "Tägliche Statistik": {
        "id": 3492,
        "allowed_buttons": ["🟡 Статистика"] # Добавляем кнопку "🟡 Статистика" сюда
    },
    "Bewertungen von GPT": {
        "id": 3479,
        "allowed_buttons": [] # нажатием этой кнопки GPT формирует ответ
    },
        "Erklärungen von Claude": {
        "id": 3481,
        "allowed_buttons": ["❓ Explain me with Claude"]
    },
        "Übersetzungen": {
        "id": 3514,
        "allowed_buttons": ["📌 Выбрать тему", "🚀 Начать перевод", "📜 Проверить перевод", "✅ Завершить перевод"]
    },
        "Nachrichten": {
        "id": 3576,
        "allowed_buttons": [] # сюда приходит по расписанию новости
    },
        "Lüstige Geschichten": {
        "id": 3582,
        "allowed_buttons": [] # сюда будут приходить по расписанию истории
    },
        "Übungen": {
        "id": 3586,
        "allowed_buttons": [] # Это на будущее тема для упражнения
    }
}


# Основное меню с ReplyKeyboardMarkup
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["📌 Выбрать тему", "🚀 Начать перевод"],
        ["📜 Проверить перевод", "✅ Завершить перевод"],
        ["🟡 Статистика"] # ✅ Кнопка статистики
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)


print(f"DEBUG: MAIN_MENU инициализировано: {MAIN_MENU.keyboard}")

# Buttons in Telegramm
TOPICS = ["Business", "Medicine", "Hobbies", "Free Time", "Education",
    "Work", "Travel", "Science", "Technology", "Everyday Life", "Random sentences"]


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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if TELEGRAM_TOKEN:
    logging.info("✅ TELEGRAM_TOKEN успешно загружен!")
else:
    logging.error("❌ TELEGRAM_TOKEN не загружен! Проверьте переменные окружения.")

# ID группы
TEST_DEEPSEEK_BOT_GROUP_CHAT_ID = int(os.getenv("TEST_DEEPSEEK_BOT_GROUP_CHAT_ID")) # Получаем как int


if TEST_DEEPSEEK_BOT_GROUP_CHAT_ID:
    logging.info(f"✅ GROUP_CHAT_ID успешно загружен: {TEST_DEEPSEEK_BOT_GROUP_CHAT_ID}")
else:
    logging.error("❌ GROUP_CHAT_ID не загружен! Проверьте переменные окружения.")


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
    # ✅ Определяем thread_id для новостей
    news_thread_id = TOPICS_TELEGRAM["Nachrichten"].get("id")
    if news_thread_id is None:
         logging.error("❌ Не удалось найти thread_id для темы Nachrichten!")
         return


    url = f"http://api.mediastack.com/v1/news?access_key={API_KEY_NEWS}&languages=de&categories=technology&countries=de,au&limit=2" # Ограничим до 3 новостей
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
                    disable_web_page_preview=False,  # Чтобы загружались превью страниц
                    message_thread_id=news_thread_id # ✅ Отправляем в топик Nachrichten
                )
        else:
            await context.bot.send_message(
                 chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
                 text="❌ Нет свежих новостей на сегодня!",
                 message_thread_id=news_thread_id # ✅ Отправляем в топик Nachrichten
                 )
    else:
        await context.bot.send_message(
            chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
            text=f"❌ Ошибка API Mediastack: {response.status_code} - {response.text}",
            message_thread_id=news_thread_id # ✅ Отправляем в топик Nachrichten
        )



# Используем контекстный менеджер для того чтобы Автоматически разрывает соединение закрывая курсор и соединения
def initialise_database():
    with get_db_connection() as connection:
        with connection.cursor() as curr:
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
                        user_id BIGINT NOT NULL,
                        username TEXT NOT NULL,
                        message TEXT NOT NULL,
                        thread_id BIGINT,
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
                        session_id BIGINT
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

            # ✅ Таблица для хранения ошибок перевода (старая, не используется детальная)
            # curr.execute("""
            #     CREATE TABLE IF NOT EXISTS translation_errors_deepseek (
            #             id SERIAL PRIMARY KEY,
            #             user_id BIGINT NOT NULL,
            #             category TEXT NOT NULL CHECK (category IN ('Грамматика', 'Лексика', 'Падежи', 'Орфография', 'Синтаксис')),
            #             error_description TEXT NOT NULL,
            #             timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            #     );
            # """)
            # ✅ Таблица для хранения запасных предложений в случае отсутствия связи Или ошибки на стороне Open AI API
            curr.execute("""
                CREATE TABLE IF NOT EXISTS spare_sentences_deepseek (
                    id SERIAL PRIMARY KEY,
                    sentence TEXT NOT NULL
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

                        severity INT DEFAULT 1,  -- Уровень серьёзности ошибки (1 — низкий, 5 — высокий)
                        mistake_count INT DEFAULT 1, -- Количество раз, когда ошибка была зафиксирована
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Время первой фиксации ошибки
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Время последнего появления ошибки
                        error_count_week INT DEFAULT 0, -- Количество ошибок за последнюю неделю

                        -- ✅ Уникальный ключ для предотвращения дубликатов
                        CONSTRAINT for_mistakes_table UNIQUE (user_id, sentence, main_category, sub_category)
                    );

            """)

    connection.commit()

    print("✅ Таблицы sentences_deepseek, translations_deepseek, daily_sentences_deepseek, messages_deepseek, user_progress_deepseek, detailed_mistakes_deepseek, spare_sentences_deepseek проверены и готовы к использованию.")

initialise_database()

async def log_all_messages(update: Update, context: CallbackContext):
    """Логируем ВСЕ текстовые сообщения для отладки."""
    try:
        if update.message and update.message.text:
            message_text = update.message.text.strip()
            message_thread_id = update.message.message_thread_id
            # Don't log commands in this generic handler
            if message_text.startswith('/'):
                return

            if message_thread_id:
                logging.info(f"📩 Бот получил сообщение в теме {message_thread_id}: {message_text}")
            else:
                logging.info(f"📩 Бот получил сообщение: {message_text}")
        else:
            logging.warning("⚠️ update.message отсутствует или пустое.")
    except Exception as e:
        logging.error(f"❌ Ошибка логирования сообщения: {e}")


#Имитация набора текста с typing-индикатором
async def simulate_typing(context, chat_id, duration=3, thread_id=None):
    """Эмулирует набор текста в чате."""
    try:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action="typing",
            message_thread_id=thread_id
        )
        await asyncio.sleep(duration)  # Имитация задержки перед отправкой текста
    except TelegramError as e:
        logging.warning(f"⚠️ Не удалось отправить typing индикатор: {e}")
    except Exception as e:
        logging.error(f"❌ Ошибка в simulate_typing: {e}")



# Buttons in Telegram
async def send_main_menu_inline(update: Update, context: CallbackContext):
    """Отправка инлайн-кнопок на основе разрешённых действий в текущей теме."""

    chat_id = update.effective_chat.id # Используем effective_chat для надежности
    message_thread_id = update.effective_message.message_thread_id # Используем effective_message

    # Определяем тему по thread_id
    topic_info = None
    for topic_name, info in TOPICS_TELEGRAM.items():
        if info.get("id") == message_thread_id:
            topic_info = info
            break

    # Если тема не найдена или нет разрешённых кнопок
    if not topic_info or not topic_info.get("allowed_buttons"):
         logging.info(f"⚠️ В теме {message_thread_id} нет разрешённых инлайн-кнопок.")
         # Optionally, you could send a message saying no inline buttons are available here
         # await context.bot.send_message(chat_id=chat_id, text="В этой теме нет специальных кнопок.", message_thread_id=message_thread_id)
         return # Просто не отправляем инлайн-кнопки


    allowed_buttons = topic_info["allowed_buttons"]

    # Создаём инлайн-кнопки из разрешённых кнопок
    buttons = [InlineKeyboardButton(button, callback_data=button) for button in allowed_buttons]

    # ✅ Располагаем кнопки по две в ряд для компактности
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # ✅ Отправляем кнопки в соответствующий thread_id
    if message_thread_id:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔘 *Выберите действие:*",
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            parse_mode="Markdown"
        )
        print(f"DEBUG: ✅ Инлайн-кнопки отправлены в поток {message_thread_id}")

    else:
        # If there's no thread_id (main chat), maybe don't send topic-specific buttons?
        # Or send them without thread_id if appropriate for the main chat
        logging.warning("⚠️ Попытка отправить инлайн-кнопки, но нет message_thread_id.")
        # await context.bot.send_message(
        #     chat_id=chat_id,
        #     text="Выберите действие:",
        #     reply_markup=reply_markup
        # )
        # print("DEBUG: Кнопки отправлены в основной чат")


async def handle_button_click(update: Update, context: CallbackContext):
    """Обрабатывает нажатия на Inline кнопки."""

    print("🛠 handle_button_click() вызван!")  # Логируем сам вызов функции

    # ✅ Всегда используем callback_query для Inline кнопок
    if not update.callback_query:
        print("❌ handle_button_click вызвана без callback_query!")
        return

    query = update.callback_query
    await query.answer() # Acknowledge the click

    chat_id = query.message.chat_id
    message_thread_id = query.message.message_thread_id # Get thread_id from the message the button was on
    user = query.from_user

    print(f"DEBUG: Нажата инлайн-кнопка: {query.data} в чате {chat_id}, потоке {message_thread_id}")

    # Determine which topic the button belongs to based on thread_id
    topic = next(
        (topic_info for topic_info in TOPICS_TELEGRAM.values() if topic_info.get("id") == message_thread_id),
        None
    )

    if topic is not None:
        allowed_buttons = topic.get("allowed_buttons", [])
        if query.data in allowed_buttons:
            print(f"DEBUG: Кнопка '{query.data}' разрешена в теме {message_thread_id}.")
            # ✅ Вызываем нужную функцию в зависимости от действия
            if query.data == "📌 Выбрать тему":
                await choose_topic(update, context) # choose_topic will get thread_id from update
            elif query.data == "🚀 Начать перевод":
                await letsgo(update, context) # letsgo will get thread_id from update
            elif query.data == "✅ Завершить перевод":
                await done(update, context) # done will get thread_id from update
            # Note: "📜 Проверить перевод" from ReplyKeyboard is handled by MessageHandler below
            elif query.data == "🟡 Статистика": # This button seems intended for ReplyKeyboard, adjust if needed
                 await user_stats(update, context) # user_stats will get thread_id from update
            elif query.data.startswith("explain:"):
                message_id = int(query.data.split(":")[1])
                logging.info(f"📌 Пользователь {user.id} запросил объяснение для message_id={message_id}")

                # ✅ Ищем в сохранённых данных
                data = context.user_data.get(f"translation_for_claude_{message_id}") # Use a specific key
                if data:
                    # ✅ Получаем текст оригинала и перевода
                    original_text = data["original_text"]
                    user_translation = data["user_translation"]
                    # ✅ Запускаем объяснение с помощью Claude, передавая update
                    await check_translation_with_claude(original_text, user_translation, update, context)

                    # ✅ Удаляем данные после успешной обработки
                    # del context.user_data[f"translation_for_claude_{message_id}"] # Keep data for potential re-explanation? Or remove to save memory? Let's remove for now.
                    print(f"✅ Удалены данные для message_id {message_id}")
                else:
                    print(f"❌ Ошибка: Данные для message_id {message_id} не найдены в context.user_data")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Не удалось найти данные для объяснения. Возможно, сообщение слишком старое.",
                        message_thread_id=message_thread_id
                    )

        else:
            print(f"DEBUG: Кнопка '{query.data}' не разрешена в данной теме ({message_thread_id}).")
            await query.edit_message_text(text=f"Кнопка '{query.data}' неактивна в этой теме.", reply_markup=None) # Remove the button after clicking
    else:
        print(f"DEBUG: Не удалось найти тему по thread_id {message_thread_id} для Inline кнопки.")
        await query.edit_message_text(text="Неизвестное действие.", reply_markup=None) # Remove the button after clicking


async def handle_reply_button_text(update: Update, context: CallbackContext):
    """Обрабатывает текстовые сообщения, соответствующие кнопкам ReplyKeyboardMarkup."""
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    message_thread_id = update.message.message_thread_id
    user_text = update.message.text.strip()

    print(f"DEBUG: Получен текст Reply кнопки: '{user_text}' в чате {chat_id}, потоке {message_thread_id}")

    # Route based on button text
    if user_text == "📌 Выбрать тему":
        await choose_topic(update, context)
    elif user_text == "🚀 Начать перевод":
        await letsgo(update, context)
    elif user_text == "📜 Проверить перевод":
        # This button press means the user is ready to check pending translations
        logging.info(f"📌 Пользователь {update.message.from_user.id} нажал кнопку '📜 Проверить перевод'. Запускаем проверку.")
        await check_translation_from_text(update, context)
    elif user_text == "✅ Завершить перевод":
        await done(update, context)
    elif user_text == "🟡 Статистика":
        await user_stats(update, context)
    # Add other Reply button texts here if any


async def start(update: Update, context: CallbackContext):
    """Запуск бота и отправка основного меню с ReplyKeyboard."""
    if update.message:
        chat_id = update.message.chat_id
        # ✅ Получаем thread_id, если он есть. Важно для тем!
        message_thread_id = update.message.message_thread_id
        logging.info(f"Received /start command in chat {chat_id}, thread {message_thread_id}")
    else:
        logger.error("❌ Нет update.message в start!")
        return

    logger.debug(f"MAIN_MENU перед отправкой: {MAIN_MENU.keyboard}")
    logger.debug(f"Отправляем сообщение с reply_markup: {MAIN_MENU.to_dict()}")

    # ✅ Отправляем сообщение с ReplyKeyboardMarkup, используя thread_id
    # Если message_thread_id None, Telegram отправит в основной чат (thread_id=1)
    sent_message = await context.bot.send_message(
        chat_id=chat_id,
        text="🚀 Добро пожаловать! Выберите действие ниже:",
        reply_markup=MAIN_MENU,
        message_thread_id=message_thread_id # ✅ Pass the thread_id here
    )
    logger.debug(f"Сообщение отправлено, message_id: {sent_message.message_id} in thread {message_thread_id}")



# === Логирование ===
async def log_message(update: Update, context: CallbackContext):
    """логируются (сохраняются) все сообщения пользователей в базе данных"""
    if not update.message: #Если update.message отсутствует, значит, пользователь отправил что-то другое (например, фото, видео, стикер).
        return #В таком случае мы не логируем это и просто выходим из функции

    user = update.message.from_user # Данные о пользователе содержит ID и имя пользователя.
    message_text = update.message.text.strip() if update.message else "" #сам текст сообщения.
    message_thread_id = update.message.message_thread_id
    chat_id = update.message.chat_id

    if not message_text:
        print("⚠️ Пустое сообщение — пропускаем логирование.")
        return

    username = user.username or f"{user.first_name or ''} {user.last_name or ''}".strip()
    # Логируем данные для диагностики
    if message_thread_id:
        print(f"📥 Получено сообщение от {username} ({user.id}) в чате {chat_id}, теме {message_thread_id}: {message_text}")
    else:
        print(f"📥 Получено сообщение от {username} ({user.id}) в чате {chat_id}: {message_text}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO messages_deepseek (user_id, username, message, thread_id)
            VALUES(%s, %s, %s, %s);
            """,
            (user.id, username, message_text, message_thread_id)
        )

        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка при записи в базу: {e}")
    finally:
        cursor.close()
        conn.close()

# утреннее приветствие членом группы
async def send_morning_reminder(context:CallbackContext):
    # ✅ Утренние приветствия обычно идут в общий чат (General)
    general_thread_id = TOPICS_TELEGRAM["General"].get("id") # None or 1

    time_now= datetime.now().time()
    # Формируем утреннее сообщение
    message = (
        f"🌅 {'Доброе утро' if time(2, 0) < time_now < time(10, 0) else ('Добрый день' if time(10, 1) < time_now < time(17, 0) else 'Добрый вечер')}!\n\n"
        "Чтобы принять участие в переводе, нажмите на кнопку 📌 Выбрать тему (через основное меню или если она доступна в теме).\n"
        "После выбора темы подтвердите начало с помощью кнопки 🚀 Начать перевод.\n\n"
        "📌 Важно:\n"
        "🔹 Отправляйте переводы в формате:\n\n"
        "1. Mein Name ist Konchita.\n"
        "2. Ich wohne in Berlin.\n\n"
        "🔹 После отправки всех предложений нажмите 📜 Проверить перевод, затем ✅ Завершить перевод чтобы зафиксировать время.\n\n"
        "🔹 В 09:00, 12:00 и 15:00 - промежуточные итоги по каждому участнику.\n\n"
        "🔹 Итоговые результаты получим в 23:30.\n\n"
        "🔹 Узнать свою статистику сразу после перевода - кнопка 🟡 Статистика.\n"
    )

    # формируем список команд ( ReplyKeyboard buttons are like commands here)
    commands = (
        "📜 **Доступные действия (ищите их в основном меню):**\n"
        "📌 Выбрать тему - Выбрать тему для перевода\n"
        "🚀 Начать перевод - Получить предложение для перевода после выбора темы.\n"
        "📜 Проверить перевод - После отправки предложений, проверить перевод\n"
        "✅ Завершить перевод - Завершить перевод и зафиксировать время.\n"
        "🟡 Статистика - Узнать свою статистику\n"
    )

    await context.bot.send_message(
        chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
        text = message,
        message_thread_id = general_thread_id # ✅ Отправляем в General
        )
    await context.bot.send_message(
        chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
        text= commands,
        message_thread_id = general_thread_id, # ✅ Отправляем в General
        parse_mode = "Markdown"
        )



async def letsgo(update: Update, context: CallbackContext):
    # Проверяем, откуда вызвана функция: через message (Reply button) или callback_query (Inline button)
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.error("❌ Нет ни message, ни callback_query в update!")
        return

    user_id = user.id
    username = user.username or user.first_name

    # ✅ Если словаря `start_times` нет — создаём его (это может быть в начале запуска бота)
    if "start_times" not in context.user_data:
        context.user_data["start_times"] = {}

    # ✅ Запоминаем время старта **для конкретного пользователя**
    context.user_data["start_times"][user_id] = datetime.now()

    # ✅ Отправляем сообщение с таймером
    timer_message = await context.bot.send_message(
        chat_id=chat_id,
        text="⏳ Время перевода: 0 мин 0 сек",
        message_thread_id=message_thread_id
    )

    # ✅ Запускаем `start_timer()` с правильными аргументами (assuming start_timer exists elsewhere)
    # asyncio.create_task(start_timer(chat_id, context, timer_message.message_id, user_id))


    # 🔹 Проверяем, выбрал ли пользователь тему (тема хранится в user_data после выбора Inline кнопкой)
    chosen_topic = context.user_data.get("chosen_topic")
    if not chosen_topic:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Вы не выбрали тему! Сначала выберите тему используя кнопку '📌 Выбрать тему'",
            message_thread_id=message_thread_id
        )
        return

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
        #await update.message.reply_animation("https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif") # GIFs require appropriate handler
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Вы уже начали перевод! Завершите его перед повторным запуском нажав на кнопку '✅ Завершить перевод'",
            message_thread_id=message_thread_id
        )
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
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Ошибка: не удалось получить предложения. Попробуйте позже.",
            message_thread_id=message_thread_id
        )
        cursor.close()
        conn.close()
        return

    # Определяем стартовый индекс (если пользователь делал /getmore - though /getmore is not implemented here)
    cursor.execute("""
        SELECT COUNT(*) FROM daily_sentences_deepseek WHERE date = CURRENT_DATE AND user_id = %s;
    """, (user_id,))
    last_index = cursor.fetchone()[0]

    # Добавляем логирование, чтобы видеть, были ли исправления
    original_sentences = sentences
    sentences = correct_numbering(sentences) # Assumes correct_numbering handles the list format

    for before, after in zip(original_sentences, sentences):
        if before != after:
            logging.info(f"⚠️ Исправлена нумерация: '{before}' → '{after}'")

    # Записываем все предложения в базу
    tasks = []
    for i, sentence in enumerate(sentences, start=last_index + 1):
        # Store in DB
        cursor.execute("""
            INSERT INTO daily_sentences_deepseek (date, sentence, unique_id, user_id, session_id)
            VALUES (CURRENT_DATE, %s, %s, %s, %s);
        """, (sentence, i, user_id, session_id))
        # Format for user display
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

    intro_text= (
    f"🚀 {user.first_name}, Вы начали перевод! Время пошло.\n\n"
    "✏️ Отправьте ваши переводы в формате: 1. Mein Name ist Konchita.\n\n"
    "Когда закончите, нажмите:\n"
    "📜 Проверить перевод\n\n"
    "✅ Завершить перевод (чтобы зафиксировать время)"
    )


    await context.bot.send_message(
        chat_id=chat_id,
        text=intro_text,
        message_thread_id=message_thread_id
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{user.first_name}, Ваши предложения:\n{task_text}",
        message_thread_id=message_thread_id
    )



# 🔹 **Функция, которая запоминает переводы, но не проверяет их**
async def handle_user_message(update: Update, context: CallbackContext):
    # ✅ Проверяем, содержит ли update.message данные
    if update.message is None or update.message.text is None:
        logging.warning("⚠️ update.message отсутствует или пустое.")
        return  # ⛔ Прерываем выполнение, если сообщение отсутствует

    user_id = update.message.from_user.id
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    message_thread_id = update.message.message_thread_id # Get thread_id

    # Check if the message is a command (e.g., /start, /stats).
    # If it is, let the command handler handle it and exit this function.
    if text.startswith('/'):
        print(f"DEBUG: Сообщение '{text}' - это команда. Пропускаем handle_user_message.")
        return # Let CommandHandler process it

    # Проверяем, является ли сообщение переводом (поддержка многострочных сообщений)
    # Regex updated to handle potential newlines within a single translation
    pattern = re.compile(r"(\d+)\.\s*(.+?)(?=\n\d+\.|$)", re.DOTALL)
    translations = pattern.findall(text)

    if translations:
        if "pending_translations" not in context.user_data:
            context.user_data["pending_translations"] = []

        found_translations = False
        for num, trans in translations:
             # Clean up each translation part
            cleaned_trans = trans.strip()
            if cleaned_trans:
                full_translation = f"{num}. {cleaned_trans}"
                context.user_data["pending_translations"].append(full_translation)
                logging.info(f"📝 Добавлен перевод: {full_translation}")
                found_translations = True

        if found_translations:
             # Send confirmation message back to the same thread
             await context.bot.send_message(
                chat_id = chat_id, # Use current chat_id
                text = ("✅ Ваш перевод сохранён.\n\n"
                "Когда будете готовы, нажмите:\n"
                "📜 Проверить перевод.\n\n"
                "✅ Завершить перевод чтобы зафиксировать время.\n"),
                message_thread_id=message_thread_id # Use current thread_id
                )
        else:
             # If pattern matched but translations were empty after stripping
             logging.warning(f"⚠️ Паттерн перевода совпал, но переводы пусты после очистки для user {user_id}. Текст: '{text}'")
             # Optionally send a message asking for correct format
             # await context.bot.send_message(...)
             pass # Do nothing if no valid translations were found

    # If the message is NOT a translation pattern and NOT a command, it's just regular text.
    # Let the log_message handler (group -1) handle logging.
    # Do NOT call handle_button_click here. Reply button text is handled by specific MessageHandlers.
    # Inline button clicks are handled by CallbackQueryHandler.
    else:
        print(f"DEBUG: Сообщение '{text}' не является переводом или командой. Пропускаем handle_user_message.")
        pass # Do nothing more in this handler


async def done(update: Update, context: CallbackContext):
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.error("❌ Нет ни message, ни callback_query в update!")
        return

    user_id = user.id

    # ✅ Даём 5 секунд на завершение записи переводов в базу данных
    logging.info(f"⌛ Ждём 5 секунд перед завершением сессии для пользователя {user_id}...")
    await asyncio.sleep(5)

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Проверяем, есть ли у пользователя активная сессия (за сегодня)
    cursor.execute("""
        SELECT session_id
        FROM user_progress_deepseek
        WHERE user_id = %s AND completed = FALSE AND start_time::date = CURRENT_DATE
        ORDER BY start_time DESC
        LIMIT 1;""",
        (user_id,))
    session = cursor.fetchone()

    if not session:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ У вас нет активных сессий за сегодня! Используйте кнопки: '📌 Выбрать тему' -> '🚀 Начать перевод' чтобы начать.",
            message_thread_id=message_thread_id
            )
        cursor.close()
        conn.close()
        return
    session_id = session[0]   # ID текущей сессии

    # ✅ Позволяем пользователю всегда завершать сессию вручную (только текущую)
    cursor.execute("""
        UPDATE user_progress_deepseek
        SET end_time = NOW(), completed = TRUE
        WHERE user_id = %s AND session_id = %s AND completed = FALSE;""",
        (user_id, session_id)) # Use session_id as well for precision
    conn.commit()

    # 🔹 Проверяем, все ли предложения переведены
    cursor.execute("""
        SELECT COUNT(*) FROM daily_sentences_deepseek
        WHERE user_id = %s AND session_id = %s;
    """, (user_id, session_id))
    total_sentences = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM translations_deepseek
        WHERE user_id = %s AND session_id = %s;
        """,(user_id, session_id))
    translated_count = cursor.fetchone()[0]

    if translated_count < total_sentences:
        await context.bot.send_message(
            chat_id=chat_id,
            text =
            (f"⚠️ Вы перевели {translated_count} из {total_sentences} предложений.\n"
            "Перевод завершён, но не все предложения переведены! Это повлияет на ваш итоговый балл."),
            message_thread_id=message_thread_id
        )
    else:
        await context.bot.send_message(
        chat_id=chat_id,
        text="✅ **Вы успешно завершили перевод! Все предложения этой сессии переведены.**",
        message_thread_id=message_thread_id
    )

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
        # Fix: Ensure regex matches only the *start* of the string
        # This regex looks for start-of-string (\d+\.) followed by optional space, then another (\d+\.)
        # It keeps the first (\1.) and replaces the rest.
        cleaned_sentence = re.sub(r"^(\d+)\.\s*\d+\.\s*", r"\1. ", sentence).strip()
        # Add another check for common issues like leading numbers without a dot or spaces
        cleaned_sentence = re.sub(r"^\d+\s+", "", cleaned_sentence).strip() # Remove leading number + space (if not 1. 2.)
        cleaned_sentence = re.sub(r"^-\s+", "", cleaned_sentence).strip() # Remove leading dash+space
        corrected_sentences.append(cleaned_sentence)
    return corrected_sentences


# Создаёт кнопки с темами (Business, Medicine, Hobbies и т. д.).
async def choose_topic(update: Update, context: CallbackContext):
    """Выводит кнопки с темами для выбора пользователем."""
    global TOPICS
    logging.info("📌 Вызвана функция choose_topic()")

    # Get chat and thread ID regardless if it's message or callback_query
    if update.message:
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.error("❌ Нет ни message, ни callback_query в update!")
        return

    # Ensure the message is sent to the 'Übersetzungen' topic
    translation_thread_id = TOPICS_TELEGRAM["Übersetzungen"].get("id")
    if translation_thread_id is None:
        logging.error("❌ Не удалось найти thread_id для темы Übersetzungen!")
        await context.bot.send_message(chat_id=chat_id, text="❌ Ошибка конфигурации: не найдена тема для переводов.", message_thread_id=message_thread_id)
        return


    # Удаляем старое сообщение с выбором темы, если оно существует
    if "topic_message_id" in context.user_data and "topic_message_chat_id" in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=context.user_data["topic_message_chat_id"], # Use saved chat_id
                message_id=context.user_data["topic_message_id"]
            )
            logging.info("✅ Удалено старое сообщение с выбором темы.")
        except Exception as e:
            logging.warning(f"⚠️ Не удалось удалить старое сообщение с выбором темы: {e}")

    # Создаём инлайн-кнопки по две в ряд для компактности
    buttons = [
        [InlineKeyboardButton(TOPICS[i], callback_data=TOPICS[i]),
         InlineKeyboardButton(TOPICS[i+1], callback_data=TOPICS[i+1])]
         for i in range(0, len(TOPICS) -1, 2)
    ]
    # Если нечётное количество тем — добавляем последнюю кнопку отдельно
    if len(TOPICS) %2 !=0:
        buttons.append([InlineKeyboardButton(TOPICS[-1], callback_data=TOPICS[-1])])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Отправляем сообщение с кнопками в топик "Übersetzungen"
    sent_message = await context.bot.send_message(
        chat_id = chat_id, # Use current chat_id (should be the group ID)
        text = "📌 Выберите тему для переводов:",
        reply_markup=reply_markup,
        message_thread_id = translation_thread_id # ✅ Отправляем в топик Übersetzungen
        )
    # Сохраняем ID сообщения и chat_id для возможности его удаления при новом вызове
    context.user_data["topic_message_id"] = sent_message.message_id
    context.user_data["topic_message_chat_id"] = chat_id


# Когда пользователь нажимает на кнопку, Telegram отправляет callback-запрос, который мы обработаем в topic_selected().
async def topic_selected(update: Update, context: CallbackContext):
    """Handles the Inline button click event when the user selects a topic."""
    query = update.callback_query
    await query.answer() # Acknowledge the click

    chosen_topic = query.data
    context.user_data["chosen_topic"] = chosen_topic

    logging.info(f"✅ Пользователь {query.from_user.id} выбрал тему: {chosen_topic}")

    # Удаляем сообщение с кнопками после выбора темы
    try:
        await context.bot.delete_message(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id
        )
        logging.info(f"✅ Сообщение с кнопками удалено после выбора темы: {chosen_topic}")

    except Exception as e:
        logging.warning(f"⚠️ Ошибка удаления сообщения с кнопками: {e}")

    # Генерация предложений сразу после выбора темы
    await letsgo(update, context) # Pass update and context



# === Функция для генерации новых предложений с помощью GPT-4 ===
async def generate_sentences(user_id, num_sentances, context: CallbackContext = None):
    client = openai.AsyncOpenAI(api_key=openai.api_key)
    #client_deepseek = OpenAI(api_key = api_key_deepseek,base_url="https://api.deepseek.com")

    # Get chosen topic from user_data if available
    chosen_topic = context.user_data.get("chosen_topic", "Random sentences")  # Default: General topic


    if chosen_topic != "Random sentences":
        prompt = f"""
        Придумай {num_sentances} связанных предложений уровня B2-C1 на тему "{chosen_topic}" на **русском языке** для перевода на **немецкий**.

        **Требования:**
        - Свяжи предложения в одну логичную историю.
        - Используй **пассивный залог** и **Konjunktiv II** В 30% предложений.
        - Каждое предложение должно быть **на отдельной строке**.
        - **НЕ добавляй перевод!** Только оригинальные русские предложения.
        - Предложения должны содержать часто употребительную в повседневной жизни лексику и грамматику.
            
        **Пример формата вывода:**
        Если бы у него был друг рядом, играть было бы веселее.
        Зная, что скоро нужно идти домой, он постарался использовать каждую минуту.
        Когда стало темнеть, он попрощался с соседским котом и побежал в дом.
        Сделав уроки, он лёг спать с мыслями о завтрашнем дне.
        """

    else:
        prompt = f"""
        Придумай {num_sentances} предложений уровня B2-C1 на **русском языке** для перевода на **немецкий**.

        **Требования:**
        - Используй **пассивный залог** и **Konjunktiv II** В 30% предложений.
        - Каждое предложение должно быть **на отдельной строке**.
        - **НЕ добавляй перевод!** Только оригинальные русские предложения.
        - Предложения должны содержать часто употребительную в повседневной жизни лексику(бизнес медицина, Хобби, Свободное время, Учёба, Работа, Путешествия) и грамматику.

        **Пример формата вывода:**
        Было бы лучше, если бы он согласился на это предложение.
        Нам сказали, что проект будет завершен через неделю.
        Если бы он мог говорить на немецком, он бы легко нашел работу.
        Сделав работу он пошёл отдыхать.
        Зная о вежливости немцев я выбрал вежливую формулировку.
        Не зная его лично, его поступок невозможно понять.
        Учитывая правила вежливости, он говорил сдержанно.
        """
    #Генерация с помощью GPT
    for attempt in range(5): # Пробуем до 5 раз при ошибке
        try:
            response = await client.chat.completions.create(
                model = "gpt-4-turbo", # or "gpt-3.5-turbo" for faster/cheaper option
                messages = [{"role": "user", "content": prompt}]
            )
            sentences = response.choices[0].message.content.split("\n")
            filtered_sentences = [s.strip() for s in sentences if s.strip()] # ✅ Фильтруем пустые строки

            if filtered_sentences:
                return filtered_sentences

        except openai.RateLimitError:
            wait_time = (attempt +1) * 2 # Задержка: 2, 4, 6 сек...
            print(f"⚠️ OpenAI API Rate Limit. Ждем {wait_time} сек...")
            await asyncio.sleep(wait_time)
        except Exception as e: # Catch other potential OpenAI errors
            logging.error(f"❌ Ошибка OpenAI при генерации предложений: {e}")
            wait_time = (attempt + 1) * 3 # Wait a bit longer for other errors
            print(f"⚠️ Ошибка OpenAI. Ждем {wait_time} сек...")
            await asyncio.sleep(wait_time)

    print("❌ Ошибка: не удалось получить ответ от OpenAI после нескольких попыток. Используем запасные предложения.")


    # # Генерация с помощью DeepSeek API ( Uncomment if you want to use DeepSeek as fallback or primary)
    # try:
    #     client_deepseek = OpenAI(api_key=api_key_deepseek, base_url="https://api.deepseek.com")
    #     for attempt in range(3): # Try DeepSeek a few times
    #         try:
    #             response = await client_deepseek.chat.completions.create(
    #                 model="deepseek-chat",
    #                 messages=[{"role": "user", "content": prompt}], stream=False
    #             )
    #             sentences = response.choices[0].message.content.split("\n")
    #             filtered_sentences = [s.strip() for s in sentences if s.strip()]
    #             if filtered_sentences:
    #                 print("✅ Успешно сгенерировано через DeepSeek.")
    #                 return filtered_sentences
    #         except Exception as e:
    #             logging.warning(f"⚠️ Ошибка DeepSeek API: {e}. Попытка {attempt+1}/3")
    #             await asyncio.sleep(5) # Wait before retrying DeepSeek
    #     print("❌ Не удалось получить ответ от DeepSeek после нескольких попыток.")
    # except Exception as e:
    #      logging.error(f"❌ Ошибка инициализации или вызова DeepSeek: {e}")
    #      print(f"❌ Ошибка инициализации или вызова DeepSeek: {e}")


    conn = get_db_connection()
    cursor = conn.cursor()

    # Fallback to spare sentences if API calls failed
    try:
        cursor.execute("""
            SELECT sentence FROM spare_sentences_deepseek ORDER BY RANDOM() LIMIT %s;""", (num_sentances,))
        spare_rows = cursor.fetchall()

        if spare_rows:
            print(f"✅ Используем {len(spare_rows)} запасных предложений.")
            return [row[0].strip() for row in spare_rows if row[0].strip()]
        else:
            print("❌ Ошибка: даже запасные предложения отсутствуют.")
            # Return a few hardcoded examples if spare sentences are also missing
            return ["Запасное предложение 1.", "Запасное предложение 2.", "Запасное предложение 3."]
    finally:
        cursor.close()
        conn.close()


async def check_translation(original_text, user_translation, update: Update, context: CallbackContext, sentence_number):
    client = openai.AsyncOpenAI(api_key=openai.api_key)

    bewertungen_von_gpt_topic_id = TOPICS_TELEGRAM["Bewertungen von GPT"].get("id") # Use .get() for safety
    if bewertungen_von_gpt_topic_id is None: # Check for None
        print("❌ Ошибка: Не найден thread_id для темы Bewertungen von GPT")
        # Fallback: Send to the thread where the command was issued? Or General?
        # Let's send to the thread where the check was initiated if topic id is missing
        target_thread_id = update.effective_message.message_thread_id
        if target_thread_id is None:
            target_thread_id = TOPICS_TELEGRAM["General"].get("id") or None # Fallback to General if command was in main chat
        await context.bot.send_message(
             chat_id=update.effective_chat.id,
             text="❌ Ошибка конфигурации: не найдена тема для оценок GPT. Отправляю сюда.",
             message_thread_id=target_thread_id
             )
        target_thread_id = target_thread_id # Use this fallback thread_id for the actual message
    else:
        target_thread_id = bewertungen_von_gpt_topic_id


    # Send initial "thinking" message to the target thread
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Ну, глянем что ты тут напереводил...",
        message_thread_id=target_thread_id
        )

    # Simulate typing in the target thread
    await simulate_typing(context, update.effective_chat.id, duration=3, thread_id=target_thread_id)


    prompt = f"""
    You are an expert German language teacher. Analyze the student's translation.

    **Original sentence (Russian):** "{original_text}"
    **User's translation (German):** "{user_translation}"

    **Your task:**
    1. **Give a score from 0 to 100** based on the original content, correct vocabulary usage, grammatical accuracy (this is the most important criterion when grading), and style. If the content is completely inaccurate, the score is zero.

    2. **Identify all mistake categories** (you may select multiple categories if needed, but STRICTLY from enumeration below, return as a comma separated string, e.g., "Nouns, Verbs"):
    - Nouns, Cases, Verbs, Tenses, Adjectives, Adverbs, Conjunctions, Prepositions, Moods, Word Order, Other mistake

    3. **Identify all specific mistake subcategories** (you may select multiple subcategories if needed, but STRICTLY from enumeration below, return as a comma separated string, e.g., "Gendered Articles, Conjugation"):

    **Fixed mistake subcategories:**
    - **Nouns:** Gendered Articles, Pluralization, Compound Nouns, Declension Errors
    - **Cases:** Nominative, Accusative, Dative, Genitive, Akkusativ + Preposition, Dative + Preposition, Genitive + Preposition
    - **Verbs:** Placement, Conjugation, Weak Verbs, Strong Verbs, Mixed Verbs, Separable Verbs, Reflexive Verbs, Auxiliary Verbs, Modal Verbs, Verb Placement in Subordinate Clause
    - **Tenses:** Present, Past, Simple Past, Present Perfect, Past Perfect, Future, Future 1, Future 2, Plusquamperfekt Passive, Futur 1 Passive, Futur 2 Passive
    - **Adjectives:** Endings, Weak Declension, Strong Declension, Mixed Declension, Placement, Comparative, Superlative, Incorrect Adjective Case Agreement
    - **Adverbs:** Placement, Multiple Adverbs, Incorrect Adverb Usage
    - **Conjunctions:** Coordinating, Subordinating, Incorrect Use of Conjunctions
    - **Prepositions:** Accusative, Dative, Genitive, Two-way, Incorrect Preposition Usage
    - **Moods:** Indicative, Declarative, Interrogative, Imperative, Subjunctive 1, Subjunctive 2
    - **Word Order:** Standard, Inverted, Verb-Second Rule, Position of Negation, Incorrect Order in Subordinate Clause, Incorrect Order with Modal Verb
    - **Other mistake:** Unclassified mistake

    4. **Provide a severity level from 1 to 5** where:
    - 1 = Minor stylistic error
    - 2 = Common mistake
    - 3 = Noticeable grammatical issue
    - 4 = Severe grammatical mistake
    - 5 = Critical mistake that changes the meaning

    5. **Provide the correct translation.**

    ---

    **Format your response STRICTLY as follows (without extra words, use newlines between fields):**
    Score: X/100
    Mistake Categories: ...
    Subcategories: ...
    Severity: ...
    Correct Translation: ...
        """


    collected_text = ""
    last_update_time = asyncio.get_running_loop().time()
    finished = False
    score = None
    categories = []
    subcategories = []
    severity = None
    correct_translation = None

    for attempt in range(3):
        try:
            stream_response = await client.chat.completions.create(
                model="gpt-4-turbo", # or gpt-3.5-turbo
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )

            async for chunk in stream_response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    new_text = chunk.choices[0].delta.content
                    collected_text += new_text

                    # Update message periodically to show progress
                    if asyncio.get_running_loop().time() - last_update_time > 2: # Update more frequently
                        try:
                            # Escape text for MarkdownV2 before editing
                            safe_text = escape_markdown_v2(collected_text)
                            # Limit text length for edit_message_text
                            if len(safe_text) > 4000: # Telegram limit is ~4096 chars
                                safe_text = safe_text[:3900] + "..." # Truncate if too long
                            await message.edit_text(safe_text, parse_mode="MarkdownV2") # Use MarkdownV2
                            last_update_time = asyncio.get_running_loop().time()
                        except TelegramError as e:
                            # Handle potential Telegram errors during edit (e.g., message modified)
                             if 'message is not modified' in str(e).lower():
                                 pass # Ignore if message hasn't changed
                             else:
                                 logging.warning(f"⚠️ Ошибка при редактировании сообщения: {e}")
                                 # If editing fails repeatedly, maybe send a new message instead?
                                 # For now, just log and continue
                        except Exception as e:
                             logging.error(f"❌ Непредвиденная ошибка при редактировании сообщения: {e}")


            # ✅ Finished streaming
            if collected_text:
                finished = True
                # Final edit after stream ends
                try:
                    safe_text = escape_markdown_v2(collected_text)
                    await message.edit_text(safe_text, parse_mode="MarkdownV2") # Final edit with MarkdownV2
                except TelegramError as e:
                     if 'message is not modified' in str(e).lower():
                         pass # Ignore if message hasn't changed
                     else:
                         logging.warning(f"⚠️ Ошибка при финальном редактировании сообщения: {e}")
                except Exception as e:
                     logging.error(f"❌ Непредвиденная ошибка при финальном редактировании сообщения: {e}")

                # ✅ Parse the full collected text
                score_match = re.search(r"Score:\s*(\d+)/100", collected_text)
                score = int(score_match.group(1)) if score_match else None

                categories_match = re.search(r"Mistake Categories:\s*(.*)", collected_text)
                categories = [cat.strip() for cat in categories_match.group(1).split(',') if cat.strip()] if categories_match else []
                # Clean categories
                categories = [re.sub(r"[^0-9a-zA-Z\s,+\-–]", "", cat).strip() for cat in categories if cat.strip()]


                subcategories_match = re.search(r"Subcategories:\s*(.*)", collected_text)
                subcategories = [subcat.strip() for subcat in subcategories_match.group(1).split(',') if subcat.strip()] if subcategories_match else []
                # Clean subcategories
                subcategories = [re.sub(r"[^0-9a-zA-Z\s,+\-–]", "", subcat).strip() for subcat in subcategories if subcat.strip()]


                severity_match = re.search(r"Severity:\s*(\d+)", collected_text)
                severity = int(severity_match.group(1)) if severity_match else None

                correct_translation_match = re.search(r"Correct Translation:\s*(.*)", collected_text, re.DOTALL) # Use DOTALL to match newlines
                correct_translation = correct_translation_match.group(1).strip() if correct_translation_match else None

                # ✅ Log parsed data
                print(f"🔎 PARSED DATA: Score={score}, Categories={categories}, Subcategories={subcategories}, Severity={severity}, Correct Translation={correct_translation[:50]}...") # Log partial translation


                # ✅ Remove the initial "thinking" message if editing was successful
                # await message.delete() # Better keep the message with the final response

                # ✅ Add Inline button after sending the message (edit the final message)
                if target_thread_id == TOPICS_TELEGRAM["Bewertungen von GPT"].get("id"): # Only add button in the GPT topic
                     # Add a key to store translation data for Claude explanation
                     message_id_for_claude = message.message_id
                     context.user_data[f"translation_for_claude_{message_id_for_claude}"] = {
                         "original_text": original_text,
                         "user_translation": user_translation
                     }
                     keyboard = [[InlineKeyboardButton("❓ Explain me with Claude", callback_data=f"explain:{message_id_for_claude}")]]
                     reply_markup = InlineKeyboardMarkup(keyboard)

                     try:
                        # Edit the final message to add the button
                        # Need to get the current text content first, or reconstruct it
                        # Or simply edit the reply_markup of the message object
                        await context.bot.edit_message_reply_markup(
                            chat_id=message.chat_id,
                            message_id=message.message_id,
                            reply_markup=reply_markup
                        )
                        print(f"✅ Added 'Explain with Claude' button to message {message.message_id}")
                     except Exception as e:
                         logging.error(f"❌ Ошибка при добавлении инлайн-кнопки к сообщению {message.message_id}: {e}")


                # ✅ Log successful check
                logging.info(f"✅ Перевод проверен для пользователя {update.effective_user.id}")

                # Return parsed results
                return collected_text, categories, subcategories, score, severity, correct_translation

            else:
                 logging.warning("⚠️ GPT returned empty response after stream.")
                 print("❌ Ошибка: GPT вернул пустой ответ.")


        except TelegramError as e:
            if 'flood control' in str(e).lower():
                wait_time = int(re.search(r'\d+', str(e)).group()) if re.search(r'\d+', str(e)) else 5
                wait_time = min(wait_time, 30) # Limit max wait time
                logging.warning(f"⚠️ Flood control exceeded. Retrying GPT check in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                 logging.error(f"❌ Telegram Error during GPT check: {e}")
                 break # Exit loop on other Telegram errors


        except openai.RateLimitError:
            wait_time = (attempt + 1) * 5
            logging.warning(f"⚠️ OpenAI API перегружен. Ждём {wait_time} сек перед повторной попыткой проверки...")
            await asyncio.sleep(wait_time)
        except Exception as e:
            logging.error(f"❌ Непредвиденная ошибка в цикле обработки GPT проверки: {e}")
            break # Exit loop on unexpected errors

    # If all attempts fail
    logging.error(f"❌ Все попытки проверки перевода для пользователя {update.effective_user.id} провалились.")
    try:
         await message.edit_text("❌ Не удалось проверить перевод. Попробуйте позже.", reply_markup=None) # Update the message indicating failure
    except Exception:
         await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось проверить перевод. Попробуйте позже.", message_thread_id=target_thread_id)

    return None, [], [], None, None, None # Return None/empty on failure


#✅ Explain with Claude
async def check_translation_with_claude(original_text, user_translation, update, context):
    # Ensure Claude API key is loaded
    if not CLAUDE_API_KEY:
        logging.error("❌ CLAUDE_API_KEY не задан. Не могу использовать Claude.")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ API ключ Claude не настроен. Не могу предоставить объяснение.",
            message_thread_id=update.effective_message.message_thread_id
            )
        return

    client = AsyncAnthropic(api_key=CLAUDE_API_KEY)

    claud_topic_id = TOPICS_TELEGRAM["Erklärungen von Claude"].get("id") # Use .get()
    if claud_topic_id is None: # Check for None
        print("❌ Ошибка: Не найден thread_id для темы 'Erklärungen von Claude'")
        # Fallback: Send to the thread where the button was clicked, or General
        target_thread_id = update.callback_query.message.message_thread_id
        if target_thread_id is None:
            target_thread_id = TOPICS_TELEGRAM["General"].get("id") or None # Fallback to General if command was in main chat
        await context.bot.send_message(
             chat_id=update.effective_chat.id,
             text="❌ Ошибка конфигурации: не найдена тема для объяснений Claude. Отправляю сюда.",
             message_thread_id=target_thread_id
             )
        target_thread_id = target_thread_id # Use this fallback thread_id for the actual message
    else:
         target_thread_id = claud_topic_id

    # Send initial "thinking" message to the target thread
    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏳ Claude анализирует перевод...",
        message_thread_id=target_thread_id
        )
    # Simulate typing in the target thread
    await simulate_typing(context, update.effective_chat.id, duration=3, thread_id=target_thread_id)

    prompt = f"""
    You are an expert in Russian and German languages, a professional translator, and a German grammar instructor.
    Your task is to analyze the student's translation from Russian to German and provide detailed feedback according to the following criteria:
    ❗ Do NOT repeat the original text or the translation in your response — only provide conclusions and explanations.
    Analysis Criteria:
    1. Errors:

    - Identify the key errors in the translation and classify them into the following categories:
        - Grammar (nouns, cases, verbs, tenses, prepositions, etc.)
        - Vocabulary (incorrect word choice, false friends, etc.)
        - Style (formal/informal register, clarity, tone, etc.)

    - Grammar Explanation:
        - Explain why the grammatical structure in the phrase is incorrect.
        - Provide a corrected version of the structure.
        - If the error is related to verb usage or prepositions, specify the correct form and usage.

    - Alternative Sentence Construction:
        - Suggest one alternative construction of the sentence.
        - Explain how the alternative differs in tone, formality, or meaning.

    - Synonyms:
        - Suggest possible synonyms for incorrect or less appropriate words.
        - Provide no more than two alternatives.
    ----------------------
    **Response Format**:
    **The response must follow this strict structured format**:
    Error 1: (Grammatical or lexical or stylistic error)
    Error 2: (Grammatical or lexical or stylistic error)
    Correct Translation: ...
    Grammar Explanation:
    Alternative Sentence Construction: ... (just a Alternative Sentence Construction without explanation)
    Synonyms:
    Original Word: ...
    Possible Synonyms: ... (no more than two)

    -------------------
    🔎 Important Instructions:

    Follow the specified format strictly.
    Provide objective and constructive feedback.
    Do NOT add introductory phrases (e.g., "Here’s what I think...").
    The response should be clear and concise.

    Below you can find:
    **Original sentence (Russian):** "{original_text}"
    **User's translation (German):** "{user_translation}"

    """
    #available_models = await client.models.list() # Use list() to check available models
    # logging.info(f"📢 Available models: {available_models}")
    # print(f"📢 Available models: {available_models}")

    model_name = "claude-3-7-sonnet-20250219" # Specify the model

    cloud_response = None
    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000, # Increase max_tokens for potentially longer explanations
                temperature=0.2
            )

            logging.info(f"📥 FULL CLAUDE RESPONSE: {response.content[0].text}")

            if response and response.content and response.content[0].text:
                cloud_response = response.content[0].text
                break
            else:
                logging.warning("⚠️ Claude returned an empty response content.")
                print("❌ Ошибка: Claude вернул пустой ответ.")
                await asyncio.sleep(5)

        except anthropic.APIError as e:
            logging.error(f"❌ API Error from Claude: {e}")
            if "authentication" in str(e).lower() or "invalid token" in str(e).lower():
                logging.error("🚨 Критическая ошибка аутентификации Claude — завершаем цикл.")
                break
            else:
                logging.warning("⚠️ Ошибка Claude. Попробуем снова через 5 секунд...")
                await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"❌ Непредвиденная ошибка при вызове Claude: {e}")
            await asyncio.sleep(5) # Wait on other errors


    if not cloud_response:
        print("❌ Ошибка: Пустой ответ от Claude после 3 попыток")
        await message.edit_text("❌ Не удалось получить объяснение от Claude. Попробуйте позже.", reply_markup=None)
        return

    # Basic formatting for the response
    formatted_response = escape_markdown_v2(cloud_response) # Escape Claude's response

    # Send to the target thread
    try:
         await message.edit_text(formatted_response, parse_mode="MarkdownV2") # Edit the thinking message
    except TelegramError as e:
         logging.warning(f"⚠️ Ошибка при редактировании сообщения для Claude: {e}. Отправляю как новое.")
         await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=formatted_response,
            message_thread_id=target_thread_id, # Send as new message to the target thread
            parse_mode="MarkdownV2"
        )
    except Exception as e:
         logging.error(f"❌ Непредвиденная ошибка при отправке ответа Claude: {e}")
         await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Не удалось отправить объяснение Claude из-за внутренней ошибки.",
            message_thread_id=target_thread_id
        )



async def log_translation_mistake(user_id, original_text, user_translation, categories, subcategories, score, severity, correct_translation):
    global VALID_CATEGORIES, VALID_SUBCATEGORIES, VALID_CATEGORIES_lower, VALID_SUBCATEGORIES_lower

    # ✅ Log raw input for debugging
    print(f"🐛 log_translation_mistake received: UserID={user_id}, Original='{original_text[:50]}...', UserTrans='{user_translation[:50]}...', Categories={categories}, Subcategories={subcategories}, Score={score}, Severity={severity}")

    # ✅ Normalize inputs to lower case for matching
    norm_categories = [cat.lower() for cat in categories]
    norm_subcategories = [subcat.lower() for subcat in subcategories]


    # ✅ Перебираем все сочетания категорий и подкатегорий из нормализованных списков
    valid_combinations = []
    for cat_lower in norm_categories:
        # Check if the category itself is valid (optional but good practice)
        if cat_lower not in VALID_CATEGORIES_lower:
            logging.warning(f"⚠️ Неизвестная категория '{cat_lower}' из GPT. Игнорируем.")
            continue

        for subcat_lower in norm_subcategories:
            # Check if the subcategory is valid for the current category
            if cat_lower in VALID_SUBCATEGORIES_lower and subcat_lower in VALID_SUBCATEGORIES_lower[cat_lower]:
                 # ✅ Add normalized values to valid_combinations
                valid_combinations.append((cat_lower, subcat_lower))
            else:
                 # If a subcategory from the list doesn't match any valid subcategory for this category
                 logging.warning(f"⚠️ Некорректная подкатегория '{subcat_lower}' для категории '{cat_lower}' из GPT. Игнорируем или добавляем как неклассифицированную.")
                 # Optionally add as unclassified if you want to log *something*
                 # valid_combinations.append(("other mistake", "unclassified mistake"))


    # ✅ If no specific valid combinations were found, add an unclassified entry
    if not valid_combinations and (norm_categories or norm_subcategories):
         logging.warning("⚠️ Не удалось найти валидные комбинации категорий/подкатегорий. Логируем как неклассифицированную ошибку.")
         valid_combinations.append(("other mistake", "unclassified mistake"))
    elif not valid_combinations and not (norm_categories or norm_subcategories):
         # This case should ideally not happen if score < 75, but as a safeguard
         logging.warning("⚠️ Нет категорий или подкатегорий, и Score < 75? Не логируем ошибку.")
         return


    # ✅ Remove duplicates from valid_combinations
    valid_combinations = list(set(valid_combinations))

    # ✅ Parse severity, default to 3 if not found
    severity = int(severity) if severity is not None and str(severity).isdigit() else 3
    severity = max(1, min(5, severity)) # Ensure severity is between 1 and 5


    # ✅ Log the final combinations to be saved
    print(f"✅ Финальные комбинации ошибок для записи ({len(valid_combinations)}):")
    for main_cat_lower, sub_cat_lower in valid_combinations:
         print(f"➡️ {main_cat_lower} - {sub_cat_lower}")


    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        for main_cat_lower, sub_cat_lower in valid_combinations:
            # Find the original casing from VALID_CATEGORIES and VALID_SUBCATEGORIES
            main_category_orig = next((cat for cat in VALID_CATEGORIES if cat.lower() == main_cat_lower), main_cat_lower)
            # Need to find the correct list of subcategories based on original main_category
            sub_category_orig = next((subcat for subcat in VALID_SUBCATEGORIES.get(main_category_orig, []) if subcat.lower() == sub_cat_lower), sub_cat_lower)


            print(f"🔍 Запись в БД: user_id={user_id}, sentence='{original_text[:50]}...', main_cat='{main_category_orig}', sub_cat='{sub_category_orig}', severity={severity}")

            cursor.execute("""
                INSERT INTO detailed_mistakes_deepseek (
                    user_id, sentence, added_data, main_category, sub_category, severity, mistake_count
                ) VALUES (%s, %s, NOW(), %s, %s, %s, 1)
                ON CONFLICT (user_id, sentence, main_category, sub_category)
                DO UPDATE SET
                    mistake_count = detailed_mistakes_deepseek.mistake_count + 1,
                    last_seen = NOW();
            """, (user_id, original_text, main_category_orig, sub_category_orig, severity))

        conn.commit()
        print(f"✅ Ошибки успешно записаны в базу detailed_mistakes_deepseek.")

    except Exception as e:
        print(f"❌ Ошибка при записи в БД detailed_mistakes_deepseek: {e}")
        logging.error(f"❌ Ошибка при записи в БД detailed_mistakes_deepseek: {e}", exc_info=True) # Log traceback
        if conn:
            conn.rollback() # Rollback changes on error

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # ✅ Логирование успешного завершения обработки
    print(f"✅ log_translation_mistake завершена.")


async def check_translation_from_text(update: Update, context: CallbackContext):
    """Handles the 'Проверить перевод' action, triggering check_user_translation."""
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.warning("⚠️ Нет ни message, ни callback_query в update!")
        return

    user_id = user.id


    # Проверяем, есть ли накопленные переводы
    if "pending_translations" not in context.user_data or not context.user_data["pending_translations"]:
        logging.info(f"❌ Пользователь {user_id} нажал '📜 Проверить перевод', но у него нет сохранённых переводов!")
        await context.bot.send_message(
            chat_id = chat_id,
            text = "❌ У вас нет непроверенных переводов! Сначала отправьте перевод, затем нажмите '📜 Проверить перевод'.",
            message_thread_id = message_thread_id
        )
        return

    logging.info(f"📌 Пользователь {user_id} нажал кнопку '📜 Проверить перевод'. Запускаем проверку переводов.")

    # ✅ Формируем переводы в нужном формате для check_user_translation
    # We need to pass the raw list, check_user_translation handles parsing
    translations_list = context.user_data["pending_translations"]

    # ✅ Очищаем список ожидающих переводов (чтобы повторно не сохранялись)
    context.user_data["pending_translations"] = []

    # ✅ Логируем перед передачей в `check_user_translation()`
    logging.info(f"📜 Передаём {len(translations_list)} переводов в check_user_translation():\n{translations_list}")

    # ✅ Отправляем список переводов в `check_user_translation()`
    await check_user_translation(update, context, translations_list)


async def check_user_translation(update: Update, context: CallbackContext, pending_translations_list=None):
    """Processes a list of user translations against original sentences."""
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.warning("⚠️ Нет ни message, ни callback_query в update.")
        return

    user_id = user.id
    username = user.first_name

    # If no list is provided, get from user_data (e.g., if called directly via /translate)
    if pending_translations_list is None:
        if "pending_translations" in context.user_data and context.user_data["pending_translations"]:
            pending_translations_list = context.user_data["pending_translations"]
            context.user_data["pending_translations"] = [] # Clear after getting
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Нет переводов для проверки. Сначала отправьте переводы.",
                message_thread_id=message_thread_id
            )
            return

    if not pending_translations_list:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Нет переводов для проверки.",
            message_thread_id=message_thread_id
        )
        return

    # Parse the list into a dictionary {sentence_number: user_translation_text}
    translations_dict = {}
    pattern = re.compile(r"(\d+)\.\s*(.+)") # Basic pattern to extract number and text
    for item in pending_translations_list:
        match = pattern.match(item)
        if match:
            num = int(match.group(1))
            text = match.group(2).strip()
            translations_dict[num] = text
        else:
             logging.warning(f"⚠️ Не удалось разобрать строку перевода: '{item}'")
             # Optionally inform the user about the problematic line
             # await context.bot.send_message(chat_id, f"⚠️ Проблема с форматом строки: '{item}'", message_thread_id=message_thread_id)

    if not translations_dict:
         await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Не удалось найти ни одного перевода в правильном формате.",
            message_thread_id=message_thread_id
        )
         return


    print(f"✅ Извлечено {len(translations_dict)} переводов для проверки: {translations_dict.keys()}")


    conn = get_db_connection()
    cursor = conn.cursor()

    # Get allowed sentence numbers for this user today
    cursor.execute("""
        SELECT unique_id, id, sentence, session_id FROM daily_sentences_deepseek
        WHERE date = CURRENT_DATE AND user_id = %s;
    """, (user_id,))

    allowed_sentences_data = {row[0]: {'id': row[1], 'sentence': row[2], 'session_id': row[3]} for row in cursor.fetchall()}

    # Check if translations for these sentences already exist today
    cursor.execute("""
        SELECT sentence_id FROM translations_deepseek
        WHERE user_id = %s AND timestamp::date = CURRENT_DATE;
    """, (user_id,))
    existing_translation_sentence_ids = {row[0] for row in cursor.fetchall()}


    results_summary = [] # For a final summary message
    processed_count = 0

    # Process each translation provided by the user
    for sentence_number, user_translation_text in translations_dict.items():
        # 1. Check if the sentence number is valid for this user today
        if sentence_number not in allowed_sentences_data:
            results_summary.append(f"❌ Предложение {sentence_number}: Не найдено или вам не принадлежит.")
            continue # Skip this translation

        sentence_info = allowed_sentences_data[sentence_number]
        sentence_id = sentence_info['id']
        original_text = sentence_info['sentence']
        session_id = sentence_info['session_id']


        # 2. Check if this sentence has already been translated by the user today
        if sentence_id in existing_translation_sentence_ids:
            results_summary.append(f"⚠️ Предложение {sentence_number}: Уже было переведено сегодня. Учитывается только первый перевод.")
            continue # Skip this translation

        logging.info(f"📌 Проверяем перевод №{sentence_number} для пользователя {user_id}: '{user_translation_text}'")

        # 3. Check translation using GPT
        # Passing the correct update, context, and sentence_number
        feedback_text, categories, subcategories, score_val, severity_val, correct_translation_val = await check_translation(
            original_text, user_translation_text, update, context, sentence_number
        )

        # Default values in case check_translation failed
        score_val = int(score_val) if score_val is not None else 0
        severity_val = int(severity_val) if severity_val is not None else None # Keep None if parsing failed

        if feedback_text:
             results_summary.append(f"📜 **Предложение {sentence_number}**: Оценено.") # Simple summary line

        # 4. Save translation result to translations_deepseek table
        try:
            cursor.execute("""
                INSERT INTO translations_deepseek (user_id, session_id, username, sentence_id, user_translation, score, feedback)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (user_id, session_id, username, sentence_id, user_translation_text, score_val, feedback_text))
            conn.commit()
            processed_count += 1
            logging.info(f"✅ Результат перевода {sentence_number} сохранен в translations_deepseek.")

            # 5. Log detailed mistakes if score is not perfect (and categories were identified)
            if score_val < 100:
                # log_translation_mistake handles score > 75 logic internally
                await log_translation_mistake(user_id, original_text, user_translation_text, categories, subcategories, score_val, severity_val, correct_translation_val)

        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении перевода {sentence_number} или логировании ошибок: {e}", exc_info=True)
            if conn:
                conn.rollback() # Rollback changes for this transaction


    cursor.close()
    conn.close()

    # Send a final message summarizing the process
    summary_message = f"✅ **Проверка переводов завершена!**\n\nОбработано: {processed_count} предложений.\n\n"
    if results_summary:
         summary_message += "Результаты:\n" + "\n".join(results_summary)
    else:
         summary_message += "Все предоставленные переводы либо уже были проверены, либо имели некорректный формат номера."


    await context.bot.send_message(
        chat_id=chat_id,
        text=summary_message,
        message_thread_id=message_thread_id
    )


async def get_original_sentences(user_id, context: CallbackContext):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Get sentences user made mistakes on frequently or recently (e.g., last week)
        # Prioritize recent mistakes, then most frequent mistakes
        cursor.execute("""
            SELECT sentence FROM detailed_mistakes_deepseek
            WHERE user_id = %s AND last_seen >= NOW() - INTERVAL '7 days' -- Mistakes in the last week
            ORDER BY mistake_count DESC, last_seen DESC
            LIMIT 3; -- Get up to 3 sentences from recent mistakes
        """, (user_id, ))
        recent_mistake_sentences = [row[0] for row in cursor.fetchall()]
        print(f"⚠️ Предложения из недавних ошибок ({len(recent_mistake_sentences)}): {recent_mistake_sentences}")

        # 2. Get general sentences from the 'sentences_deepseek' pool
        num_general_sentences_needed = 7 - len(recent_mistake_sentences)
        general_sentences = []
        if num_general_sentences_needed > 0:
            cursor.execute("""
                SELECT sentence FROM sentences_deepseek ORDER BY RANDOM() LIMIT %s;""", (num_general_sentences_needed,))
            general_sentences = [row[0] for row in cursor.fetchall()]
            print(f"📌 Найдено в базе общих предложений ({len(general_sentences)}): {general_sentences}")


        # 3. If still need more, generate via GPT
        num_gpt_sentences_needed = 7 - len(recent_mistake_sentences) - len(general_sentences)
        gpt_sentences = []
        if num_gpt_sentences_needed > 0:
            print(f"⚠️ Генерируем ещё {num_gpt_sentences_needed} предложений через GPT...")
            gpt_sentences = await generate_sentences(user_id, num_gpt_sentences_needed, context)
            print(f"🚀 Сгенерированные GPT предложения ({len(gpt_sentences)}): {gpt_sentences}")


        # Combine and shuffle the list
        final_sentences = recent_mistake_sentences + general_sentences + gpt_sentences
        # Shuffle to mix mistake sentences and new ones
        import random
        random.shuffle(final_sentences)

        # Ensure we don't exceed 7 sentences (just in case, though logic should prevent it)
        final_sentences = final_sentences[:7]

        print(f"✅ Финальный список предложений для пользователя {user_id} ({len(final_sentences)}): {final_sentences}")

        if not final_sentences:
            print("❌ Ошибка: Не удалось получить предложения!")
            # Fallback to hardcoded if everything fails
            return ["Не удалось получить предложения. Попробуйте снова.", "Пожалуйста, сообщите администратору о проблеме."]

        return final_sentences

    except Exception as e:
        logging.error(f"❌ Ошибка в get_original_sentences: {e}", exc_info=True)
        print(f"❌ Ошибка в get_original_sentences: {e}")
        # Fallback to hardcoded if any error occurs during DB/API
        return ["Произошла ошибка при получении предложений. Попробуйте снова.", "Пожалуйста, сообщите администратору о проблеме."]

    finally: # Close cursor and connection
        cursor.close()
        conn.close()

# Указываем ID нужных каналов
PREFERRED_CHANNELS = [
    "UCthmoIZKvuR1-KuwednkjHg",  # Deutsch mit Yehor
    "UCHLkEhIoBRu2JTqYJlqlgbw",  # Deutsch mit Rieke
    "UCeVQK7ZPXDOAyjY0NYqmX-Q"   # Benjamin - Der Deutschlehrer
]

def search_youtube_videous(topic, max_results=5):
    query=topic
    if not YOUTUBE_API_KEY:
        print("❌ Ошибка: YOUTUBE_API_KEY не задан!")
        return ["❌ Ошибка конфигурации: YouTube API ключ не задан."]
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
                channelId=channal_id,
                relevanceLanguage="de", # Prioritize German
                regionCode="DE" # Prioritize Germany
            )
            response = request.execute()

            for item in response.get("items", []):
                title = item["snippet"]["title"]
                # title = title.replace('{', '{{').replace('}', '}}') # Escape for f-string (not needed for MarkdownV2)
                # title = title.replace('%', '%%') # Escape % (not needed for MarkdownV2)
                video_id = item["id"].get("videoId", "") # Безопасное извлечение videoId
                if video_id:
                    # Store video_id and title
                    video_data.append({'title': title, 'video_id': video_id})

        # If not enough videos found on preferred channels, search more broadly
        if len(video_data) < max_results:
            print(f"❌ Недостаточно видео ({len(video_data)}) на приоритетных каналах. Ищем ещё {max_results - len(video_data)} по всем каналам.")
            request = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=max_results - len(video_data), # Get fewer from general search
                relevanceLanguage="de",
                regionCode="DE"
            )
            response = request.execute()

            for item in response.get("items", []):
                title = item["snippet"]["title"]
                # title = title.replace('{', '{{').replace('}', '}}') # Escape for f-string (not needed for MarkdownV2)
                # title = title.replace('%', '%%') # Escape % (not needed for MarkdownV2)
                video_id = item["id"].get("videoId", "") # Безопасное извлечение videoId
                 # Avoid adding duplicates if a video appeared in both searches
                if video_id and video_id not in [v['video_id'] for v in video_data]:
                    video_data.append({'title': title, 'video_id': video_id})


        if not video_data:
            return ["❌ Видео по этой теме не найдено. Попробуйте позже или выберите другую тему."]

        # ✅ Теперь получаем количество просмотров для всех найденных видео
        video_ids = ",".join([video['video_id'] for video in video_data if video['video_id']])
        if video_ids:
            try:
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
            except Exception as e:
                logging.warning(f"⚠️ Не удалось получить статистику YouTube: {e}")
                print(f"⚠️ Не удалось получить статистику YouTube: {e}")
                # Continue without view counts if API fails

        # ✅ Подставляем значение по умолчанию (если данных о просмотрах нет)
        for video in video_data:
            video.setdefault("views", 0)

        # ✅ Сортируем по количеству просмотров (по убыванию)
        sorted_videos = sorted(video_data, key=lambda x: x["views"], reverse=True)

        # ✅ Возвращаем только 2 самых популярных видео
        top_videos = sorted_videos[:2]

        # ✅ Формируем ссылки в Telegram-формате MarkdownV2
        preferred_videos_markdown = [
            f"[▶️ {escape_markdown_v2(video['title'])}]({escape_markdown_v2('https://www.youtube.com/watch?v=' + video['video_id'])})"
            for video in top_videos if video.get('video_id')
        ]

        return preferred_videos_markdown # Return list of MarkdownV2 links

    except Exception as e:
        logging.error(f"❌ Ошибка при поиске видео в YouTube: {e}", exc_info=True)
        print(f"❌ Ошибка при поиске видео в YouTube: {e}")
        return ["❌ Произошла ошибка при поиске видео в YouTube."]


#📌 this function will filter and rate mistakes
async def rate_mistakes(user_id):
    # ✅ Ensure user_id is an integer
    if not isinstance(user_id, int):
         logging.error(f"❌ Ошибка: Некорректный user_id ({user_id}, тип {type(user_id)}) в rate_mistakes.")
         return 0, 'неизвестно', 0, 'неизвестно', 'неизвестно'


    with get_db_connection() as conn:
        with conn.cursor() as cursor:

            # ✅ 1. Calculate amount of translated sentences of the user in a week
            cursor.execute("""
                SELECT COUNT(DISTINCT sentence_id) -- Use DISTINCT sentence_id to count unique sentences translated
                FROM translations_deepseek
                WHERE user_id = %s AND timestamp >= NOW() - INTERVAL '7 days'; -- Last 7 full days
            """, (user_id,))
            total_sentences_translated = cursor.fetchone()[0] or 0

            # ✅ 2. Calculate total sentences assigned in the last week
            cursor.execute("""
                 SELECT COUNT(DISTINCT id)
                 FROM daily_sentences_deepseek
                 WHERE user_id = %s AND date >= CURRENT_DATE - INTERVAL '7 days';
            """, (user_id,))
            total_sentences_assigned = cursor.fetchone()[0] or 0


            # ✅ 3. Calculate all mistakes KPI within a week (last 7 days)
            cursor.execute("""
                WITH user_mistakes AS (
                    SELECT main_category, sub_category, COUNT(*) AS mistake_count
                    FROM detailed_mistakes_deepseek
                    WHERE user_id = %s
                    AND last_seen >= NOW() - INTERVAL '7 days'
                    GROUP BY main_category, sub_category
                ),
                ranked_categories AS (
                    SELECT
                        main_category,
                        SUM(mistake_count) AS total_main_category_mistakes,
                        ROW_NUMBER() OVER (ORDER BY SUM(mistake_count) DESC) as rank
                    FROM user_mistakes
                    GROUP BY main_category
                    ORDER BY total_main_category_mistakes DESC
                ),
                top_main_category AS (
                     SELECT main_category FROM ranked_categories WHERE rank = 1
                ),
                top_subcategories AS (
                    SELECT
                        sub_category,
                        mistake_count,
                        ROW_NUMBER() OVER (ORDER BY mistake_count DESC) as sub_rank
                    FROM user_mistakes
                    WHERE main_category = (SELECT main_category FROM top_main_category) -- Filter by the top main category
                    ORDER BY mistake_count DESC
                    LIMIT 2
                )
                -- ✅ FINAL QUERY TO SELECT ALL PIECES
                SELECT
                    (SELECT SUM(mistake_count) FROM user_mistakes) AS total_mistakes_week, -- Total mistakes in the week
                    (SELECT main_category FROM top_main_category) AS top_mistake_category,
                    (SELECT total_main_category_mistakes FROM ranked_categories WHERE rank = 1) AS number_of_top_category_mistakes, -- Correct count for the top category
                    (SELECT sub_category FROM top_subcategories WHERE sub_rank = 1) AS top_subcategory_1,
                    (SELECT sub_category FROM top_subcategories WHERE sub_rank = 2) AS top_subcategory_2
                ;
            """, (user_id,))

            result = cursor.fetchone()
            if result is not None:
                # Unpack with default values in case query parts return NULL
                mistakes_week = result[0] if result[0] is not None else 0
                top_mistake_category = result[1] if result[1] is not None else 'неизвестно'
                number_of_top_category_mistakes = result[2] if result[2] is not None else 0
                top_mistake_subcategory_1 = result[3] if result[3] is not None else 'неизвестно'
                top_mistake_subcategory_2 = result[4] if result[4] is not None else 'неизвестно'
            else:
                # If no mistake data for the week
                mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2 = 0, 'неизвестно', 0, 'неизвестно', 'неизвестно'


    # Calculate missed sentences
    missed_week = GREATEST(0, total_sentences_assigned - total_sentences_translated)


    return total_sentences_translated, mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2, missed_week


# Using Telegram's built-in helper for MarkdownV2 escaping
# from telegram.helpers import escape_markdown_v2

# This function already imported at the top


# 📌📌📌📌📌
async def send_me_analytics_and_recommend_me(context: CallbackContext):
    client = openai.AsyncOpenAI(api_key=openai.api_key)

    # ✅ Determine the thread_id for recommendations
    recommendations_thread_id = TOPICS_TELEGRAM["Empfehlungen"].get("id")
    if recommendations_thread_id is None:
         logging.error("❌ Не удалось найти thread_id для темы Empfehlungen!")
         # Fallback? Or just skip sending recommendations? Let's skip for now.
         return


    #get all user_id's from _DB who had mistakes in the last week
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            SELECT DISTINCT user_id FROM detailed_mistakes_deepseek
            WHERE last_seen >= NOW() - INTERVAL '7 days';
            """)
            user_ids_with_mistakes = [row[0] for row in cursor.fetchall()]

             # Also get users who translated but had no mistakes (to include them in count)
            cursor.execute("""
            SELECT DISTINCT user_id FROM translations_deepseek
            WHERE timestamp >= NOW() - INTERVAL '7 days'
            AND user_id NOT IN (SELECT user_id FROM detailed_mistakes_deepseek WHERE last_seen >= NOW() - INTERVAL '7 days');
            """)
            user_ids_translated_no_mistakes = [row[0] for row in cursor.fetchall()]

    # Combine all relevant user IDs and get unique ones
    all_user_ids_this_week = list(set(user_ids_with_mistakes + user_ids_translated_no_mistakes))


    if not all_user_ids_this_week:
        print("❌ Нет пользователей с активностью (переводы/ошибки) за последнюю неделю.")
        await context.bot.send_message(
             chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
             text="📈 За последнюю неделю нет данных по переводам или ошибкам.",
             message_thread_id=recommendations_thread_id
             )
        return

    for user_id in all_user_ids_this_week:
        # Get statistics for the user
        total_sentences_translated, mistakes_week, top_mistake_category, number_of_top_category_mistakes, top_mistake_subcategory_1, top_mistake_subcategory_2, missed_week = await rate_mistakes(user_id)

        # Get username
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT username FROM translations_deepseek WHERE user_id = %s LIMIT 1;""",
                    (user_id, ))
                result = cursor.fetchone()
                username = result[0] if result else f"Пользователь {user_id}" # Fallback username


        # ✅ Запрашиваем тему для рекомендаций у OpenAI только если были ошибки
        topic = None
        if mistakes_week > 0 and (top_mistake_category != 'неизвестно' or top_mistake_subcategory_1 != 'неизвестно'):
             prompt = f"""
            Ты эксперт по изучению грамматики немецкого языка.
            Пользователь допустил следующие ошибки за последнюю неделю:

            - **Категория ошибки:** {top_mistake_category}
            - **Первая подкатегория:** {top_mistake_subcategory_1}
            - **Вторая подкатегория:** {top_mistake_subcategory_2}

            Определи для пользователя тему грамматики для проработки и изучение на основе этих данных (например, "Plusquamperfekt", "Konjunktiv II", "Dativ Präpositionen").
            **Выводи только одно слово или короткую фразу на НЕМЕЦКОМ языке, соответствующую теме.**
            Если ошибки не указывают на конкретную тему грамматики, предложи общую тему, например "Deutsche Grammatik B2" или "Wortschatz lernen".
            """

             for attempt in range(3): # Try up to 3 times for topic generation
                try:
                    response = await client.chat.completions.create(
                    model="gpt-4-turbo", # or gpt-3.5-turbo
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50 # Limit response length
                    )
                    topic = response.choices[0].message.content.strip()
                    print(f"📌 Определена тема для рекомендаций для пользователя {user_id}: {topic}")
                    break # Exit loop on success
                except openai.RateLimitError:
                    wait_time = (attempt + 1) * 5
                    logging.warning(f"⚠️ OpenAI API перегружен при запросе темы. Ждём {wait_time} сек...")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    logging.error(f"❌ Ошибка OpenAI при генерации темы для пользователя {user_id}: {e}", exc_info=True)
                    wait_time = (attempt + 1) * 3
                    await asyncio.sleep(wait_time) # Wait on other errors

        # ✅ Ищем видео на YouTube только если тема была определена
        valid_links = ["_Видео-рекомендации:_"] # Start with a header
        if topic:
             video_data = search_youtube_videous(topic) # This function returns MarkdownV2 links or error strings
             valid_links.extend(video_data) # Add the search results

        if len(valid_links) == 1: # Only the header is present means no videos were found
             valid_links.append("❌ Не удалось найти видео по этой теме.")


        # ✅ Формируем сообщение для пользователя
        recommendations = (
            f"📈 *Недельный отчёт для {escape_markdown_v2(username)}*\n\n" # Escape username for MarkdownV2
            f"📜 *Предложений задано за неделю:* {total_sentences_assigned}\n"
            f"✅ *Переведено:* {total_sentences_translated}\n"
            f"🚨 *Не переведено:* {missed_week}\n"
            f"🔴 *Всего ошибок за неделю:* {mistakes_week}\n"
        )

        if mistakes_week > 0:
             recommendations += (
                f"📊 *Основные проблемы:*\n"
                f"🥇 *Категория с наибольшим числом ошибок* ({number_of_top_category_mistakes}): {escape_markdown_v2(top_mistake_category)}\n"
             )
             if top_mistake_subcategory_1 != 'неизвестно':
                recommendations += f"🥈 *Частые подкатегории:* {escape_markdown_v2(top_mistake_subcategory_1)}\n"
             if top_mistake_subcategory_2 != 'неизвестно':
                 recommendations += f"🥉 *Вторые по частоте подкатегории:* {escape_markdown_v2(top_mistake_subcategory_2)}\n"
        else:
             recommendations += f"✨ *Отличная работа! За последнюю неделю нет зафиксированных ошибок.*\n"


        if topic:
             recommendations += (f"\n🧐 *Рекомендуемая тема для изучения на основе ошибок:*\n `{escape_markdown_v2(topic)}`\n\n") # Escape topic for MarkdownV2 and use code block
             recommendations += "\n".join(valid_links) # Add video links (already in MarkdownV2)
        else:
             recommendations += "\n\n" + "\n".join(valid_links) # Add video links (already in MarkdownV2, even if it's just the error message)


        #Debugging...
        print("DEBUG Recommendations message:\n", recommendations)


        # ✅ Отправляем сообщение пользователю в топик "Empfehlungen"
        try:
            await context.bot.send_message(
                chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
                text=recommendations,
                parse_mode = "MarkdownV2", # Use MarkdownV2
                message_thread_id=recommendations_thread_id # ✅ Отправляем в топик Empfehlungen
                )
        except TelegramError as e:
             logging.error(f"❌ Telegram Error при отправке рекомендаций пользователю {user_id}: {e}", exc_info=True)
             print(f"❌ Telegram Error при отправке рекомендаций пользователю {user_id}: {e}")
             # Fallback: send to general chat or handle error

        except Exception as e:
             logging.error(f"❌ Непредвиденная ошибка при отправке рекомендаций пользователю {user_id}: {e}", exc_info=True)
             print(f"❌ Непредвиденная ошибка при отправке рекомендаций пользователю {user_id}: {e}")



# SQL Запрос проверено
async def send_weekly_summary(context: CallbackContext):

    # ✅ Определяем thread_id для еженедельной статистики
    weekly_stats_thread_id = TOPICS_TELEGRAM["Wöchenliche Statistik"].get("id")
    if weekly_stats_thread_id is None:
         logging.error("❌ Не удалось найти thread_id для темы Wöchenliche Statistik!")
         return

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Собираем статистику за последнюю неделю (last 7 days)
    # Include users who had sentences assigned but didn't translate
    cursor.execute("""
        WITH AllUsersWithSentences AS (
             SELECT DISTINCT user_id
             FROM daily_sentences_deepseek
             WHERE date >= CURRENT_DATE - INTERVAL '7 days' -- Sentences assigned in the last 7 days
        ),
        UserTranslationStats AS (
            SELECT
                t.user_id,
                t.username,
                COUNT(DISTINCT t.sentence_id) AS translated_count,
                COALESCE(AVG(t.score), 0) AS avg_score
            FROM translations_deepseek t
            WHERE t.timestamp >= CURRENT_DATE - INTERVAL '7 days' -- Translations in the last 7 days
            GROUP BY t.user_id, t.username
        ),
        UserProgressStats AS (
            SELECT
                user_id,
                AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time,
                SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time
            FROM user_progress_deepseek
            WHERE completed = TRUE -- Only completed sessions
            AND start_time >= CURRENT_DATE - INTERVAL '7 days' -- Sessions started in the last 7 days
            GROUP BY user_id
        ),
        UserAssignedSentences AS (
            SELECT
                user_id,
                COUNT(DISTINCT id) AS assigned_count
            FROM daily_sentences_deepseek
            WHERE date >= CURRENT_DATE - INTERVAL '7 days' -- Sentences assigned in the last 7 days
            GROUP BY user_id
        )
        -- Final Select joining all CTEs
        SELECT
            au.user_id,
            COALESCE(uts.username, (SELECT username FROM messages_deepseek WHERE user_id = au.user_id LIMIT 1), 'Неизвестный пользователь'), -- Get username from translations or messages
            COALESCE(uas.assigned_count, 0) AS всего_предложений,
            COALESCE(uts.translated_count, 0) AS переведено,
            GREATEST(0, COALESCE(uas.assigned_count, 0) - COALESCE(uts.translated_count, 0)) AS пропущено_за_неделю,
            COALESCE(uts.avg_score, 0) AS средняя_оценка,
            COALESCE(ups.avg_time, 0) AS среднее_время_сессии_в_минутах,
            COALESCE(ups.total_time, 0) AS общее_время_в_минутах,
            -- Calculate final score: avg_score - (avg_time * 2) - (missed * 20)
            COALESCE(uts.avg_score, 0)
            - (COALESCE(ups.avg_time, 0) * 2)
            - (GREATEST(0, COALESCE(uas.assigned_count, 0) - COALESCE(uts.translated_count, 0)) * 20) AS итоговый_балл
        FROM AllUsersWithSentences au
        LEFT JOIN UserTranslationStats uts ON au.user_id = uts.user_id
        LEFT JOIN UserProgressStats ups ON au.user_id = ups.user_id
        LEFT JOIN UserAssignedSentences uas ON au.user_id = uas.user_id
        ORDER BY итоговый_балл DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        await context.bot.send_message(
             chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
             text="📊 За последнюю неделю никто не перевел ни одного предложения!",
             message_thread_id=weekly_stats_thread_id # ✅ Отправляем в топик Wöchenliche Statistik
             )
        return

    summary = "🏆 Итоги недели:\n\n"

    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, username, total_assigned, translated, missed, avg_score, avg_minutes, total_minutes, final_score) in enumerate(rows):
        medal = medals[i] if i < len(medals) else "💩"
        # Escape username for Markdown
        safe_username = escape_markdown(username)
        summary += (
            f"{medal} {safe_username}\n"
            f"📜 Предложений задано: {total_assigned}\n"
            f"✅ Переведено: {translated}\n"
            f"🚨 Пропущено: {missed}\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общее: {total_minutes:.1f} мин\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )

    await context.bot.send_message(
         chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
         text=summary,
         message_thread_id=weekly_stats_thread_id, # ✅ Отправляем в топик Wöchenliche Statistik
         parse_mode = "Markdown" # Use Markdown
         )


async def user_stats(update: Update, context: CallbackContext):
    """Sends daily and weekly statistics for the user."""
    if update.message:
        user = update.message.from_user
        chat_id = update.message.chat_id
        message_thread_id = update.message.message_thread_id
    elif update.callback_query:
        user = update.callback_query.from_user
        chat_id = update.callback_query.message.chat_id
        message_thread_id = update.callback_query.message.message_thread_id
    else:
        logging.error("❌ Нет ни message, ни callback_query в update!")
        return

    user_id = user.id
    username = user.first_name

    conn = get_db_connection()
    cursor = conn.cursor()

    # 📌 Статистика за сегодняшний день
    cursor.execute("""
        WITH UserDailySentences AS (
            SELECT COUNT(DISTINCT id) AS total_assigned
            FROM daily_sentences_deepseek
            WHERE user_id = %s AND date = CURRENT_DATE
        ),
        UserDailyTranslations AS (
             SELECT
                 COUNT(DISTINCT sentence_id) AS translated_count,
                 COALESCE(AVG(score), 0) AS avg_score
             FROM translations_deepseek
             WHERE user_id = %s AND timestamp::date = CURRENT_DATE
        ),
        UserDailyProgress AS (
             SELECT
                 COALESCE(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0) AS avg_time,
                 COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0) AS total_time
             FROM user_progress_deepseek
             WHERE user_id = %s AND start_time::date = CURRENT_DATE AND completed = TRUE
        )
        SELECT
             COALESCE(uds.total_assigned, 0) AS total_assigned_today,
             COALESCE(udt.translated_count, 0) AS translated_today,
             GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) AS missed_today,
             COALESCE(udt.avg_score, 0) AS avg_score_today,
             COALESCE(udp.avg_time, 0) AS avg_time_today_minutes,
             COALESCE(udp.total_time, 0) AS total_time_today_minutes,
             -- Calculate daily final score: avg_score - (avg_time * 2) - (missed * 20)
             COALESCE(udt.avg_score, 0)
             - (COALESCE(udp.avg_time, 0) * 2)
             - (GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) * 20) AS final_score_today
        FROM UserDailySentences uds, UserDailyTranslations udt, UserDailyProgress udp;
    """, (user_id, user_id, user_id))

    today_stats = cursor.fetchone()


    # 📌 Недельная статистика (last 7 days) - Reusing the logic from send_weekly_summary but filtered by user
    cursor.execute("""
        WITH UserWeeklySentences AS (
             SELECT COUNT(DISTINCT id) AS total_assigned
             FROM daily_sentences_deepseek
             WHERE user_id = %s AND date >= CURRENT_DATE - INTERVAL '7 days'
        ),
        UserWeeklyTranslations AS (
             SELECT
                 COUNT(DISTINCT sentence_id) AS translated_count,
                 COALESCE(AVG(score), 0) AS avg_score
             FROM translations_deepseek
             WHERE user_id = %s AND timestamp >= CURRENT_DATE - INTERVAL '7 days'
             GROUP BY user_id -- Group by user_id (redundant here as we filter by user_id)
        ),
        UserWeeklyProgress AS (
             SELECT
                 COALESCE(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0) AS avg_time,
                 COALESCE(SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0) AS total_time
             FROM user_progress_deepseek
             WHERE user_id = %s AND completed = TRUE
             AND start_time >= CURRENT_DATE - INTERVAL '7 days'
             GROUP BY user_id -- Group by user_id
        )
        SELECT
             COALESCE(uws.total_assigned, 0) AS total_assigned_week,
             COALESCE(uwt.translated_count, 0) AS translated_week,
             GREATEST(0, COALESCE(uws.total_assigned, 0) - COALESCE(uwt.translated_count, 0)) AS missed_week,
             COALESCE(uwt.avg_score, 0) AS avg_score_week,
             COALESCE(uwp.avg_time, 0) AS avg_time_week_minutes,
             COALESCE(uwp.total_time, 0) AS total_time_week_minutes,
             -- Calculate weekly final score: avg_score - (avg_time * 2) - (missed * 20)
             COALESCE(uwt.avg_score, 0)
             - (COALESCE(uwp.avg_time, 0) * 2)
             - (GREATEST(0, COALESCE(uws.total_assigned, 0) - COALESCE(uwt.translated_count, 0)) * 20) AS final_score_week
        FROM UserWeeklySentences uws, UserWeeklyTranslations uwt, UserWeeklyProgress uwp;
    """, (user_id, user_id, user_id))

    weekly_stats = cursor.fetchone()

    cursor.close()
    conn.close()

    # 📌 Формирование ответа
    stats_text = f"📊 Ваша статистика, {username}:\n\n"

    if today_stats:
        stats_text += (
            f"📅 **Сегодня**\n"
            f"📜 Задано: {today_stats[0]}\n"
            f"✅ Переведено: {today_stats[1]}\n"
            f"🚨 Пропущено: {today_stats[2]}\n"
            f"🎯 Средняя оценка: {today_stats[3]:.1f}/100\n"
            f"⏱ Среднее время сессии: {today_stats[4]:.1f} мин\n"
            f"⏱ Общее время: {today_stats[5]:.1f} мин\n"
            f"🏆 Итоговый балл: {today_stats[6]:.1f}\n"
        )
    else:
        stats_text += f"📅 **Сегодня**\n❌ Нет данных (вы ещё не переводили или не завершали сессии)."

    stats_text += "\n" # Add a newline between daily and weekly

    if weekly_stats:
         # Check if there was any activity assigned/translated/progress in the week
         if weekly_stats[0] > 0 or weekly_stats[1] > 0 or weekly_stats[5] > 0:
            stats_text += (
                f"📆 **Последние 7 дней**\n"
                f"📜 Задано: {weekly_stats[0]}\n"
                f"✅ Переведено: {weekly_stats[1]}\n"
                f"🚨 Пропущено: {weekly_stats[2]}\n"
                f"🎯 Средняя оценка: {weekly_stats[3]:.1f}/100\n"
                f"⏱ Среднее время сессии: {weekly_stats[4]:.1f} мин\n"
                f"⏱ Общее время: {weekly_stats[5]:.1f} мин\n"
                f"🏆 Итоговый балл: {weekly_stats[6]:.1f}\n"
            )
         else:
             stats_text += f"📆 **Последние 7 дней**\n❌ Нет данных (нет активности)."

    else:
        stats_text += "\n📆 **Последние 7 дней**\n❌ Нет данных (нет активности)."

    await context.bot.send_message(
        chat_id=chat_id,
        text=stats_text,
        message_thread_id=message_thread_id,
        parse_mode = "Markdown" # Use Markdown
        )


async def send_daily_summary(context: CallbackContext):
    # ✅ Определяем thread_id для ежедневной статистики
    daily_stats_thread_id = TOPICS_TELEGRAM["Tägliche Statistik"].get("id")
    if daily_stats_thread_id is None:
         logging.error("❌ Не удалось найти thread_id для темы Tägliche Statistik!")
         return


    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Получаем всех пользователей, которые писали в чат **за сегодня** (to include lazy ones today)
    cursor.execute("""
        SELECT DISTINCT user_id, username
        FROM messages_deepseek
        WHERE timestamp::date = CURRENT_DATE;
    """)
    all_users_today_interacted = {int(row[0]): row[1] for row in cursor.fetchall()}


    # 🔹 Собираем статистику по пользователям **за сегодня**
    cursor.execute("""
       WITH UserDailySentences AS (
            SELECT user_id, COUNT(DISTINCT id) AS total_assigned
            FROM daily_sentences_deepseek
            WHERE date = CURRENT_DATE
            GROUP BY user_id
       ),
       UserDailyTranslations AS (
            SELECT
                t.user_id,
                COUNT(DISTINCT t.id) AS translated_count,
                COALESCE(AVG(t.score), 0) AS avg_score
            FROM translations_deepseek t
            WHERE t.timestamp::date = CURRENT_DATE
            GROUP BY t.user_id
       ),
       UserDailyProgress AS (
            SELECT user_id,
                AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time,
                SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time
            FROM user_progress_deepseek
            WHERE completed = true AND start_time::date = CURRENT_DATE
            GROUP BY user_id
       )
       SELECT
            uds.user_id,
            COALESCE(uds.total_assigned, 0) AS total_sentences,
            COALESCE(udt.translated_count, 0) AS translated,
            GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) AS missed,
            COALESCE(udp.avg_time, 0) AS avg_time_minutes,
            COALESCE(udp.total_time, 0) AS total_time_minutes,
            COALESCE(udt.avg_score, 0) AS avg_score,
            COALESCE(udt.avg_score, 0)
            - (COALESCE(udp.avg_time, 0) * 2)
            - (GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) * 20) AS final_score
       FROM UserDailySentences uds
       LEFT JOIN UserDailyTranslations udt ON uds.user_id = udt.user_id
       LEFT JOIN UserDailyProgress udp ON uds.user_id = udp.user_id
       ORDER BY final_score DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # 🔹 Identify users who had sentences assigned but didn't translate (lazy ones)
    assigned_users_ids = {row[0] for row in rows} # Users who were assigned sentences today
    lazy_users_today = {uid: uname for uid, uname in all_users_today_interacted.items() if uid not in assigned_users_ids}


    # 🔹 Formulate the report
    if not rows and not lazy_users_today:
        await context.bot.send_message(
             chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
             text="📊 Сегодня никто не переводил и не писал в чат!",
             message_thread_id=daily_stats_thread_id
             )
        return

    summary = "📊 Итоги дня:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, total_sentences, translated, missed, avg_minutes, total_time_minutes, avg_score, final_score) in enumerate(rows):
        username = all_users_today_interacted.get(int(user_id), f'Неизвестный пользователь {user_id}') # Get username, fallback if needed
        medal = medals[i] if i < len(medals) else "💩"
        # Escape username for Markdown
        safe_username = escape_markdown(username)
        summary += (
            f"{medal} {safe_username}\n"
            f"📜 Задано: {total_sentences}\n"
            f"✅ Переведено: {translated}\n"
            f"🚨 Не переведено: {missed}\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общ.: {total_time_minutes:.1f} мин\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )


    # 🚨 **Добавляем блок про ленивых (писали в чат, но не были assigned sentences today)**
    if lazy_users_today:
        summary += "\n🦥 Ленивцы (писали в чат сегодня, но не начали перевод):\n"
        for username in lazy_users_today.values():
            summary += f"👤 {escape_markdown(username)}: нет данных по переводу сегодня!\n"

    await context.bot.send_message(
        chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
        text=summary,
        message_thread_id=daily_stats_thread_id, # ✅ Отправляем в топик Tägliche Statistik
        parse_mode = "Markdown" # Use Markdown
        )



async def send_progress_report(context: CallbackContext):
    # ✅ Определяем thread_id для ежедневной промежуточной статистики (тот же, что и для итогов дня)
    progress_report_thread_id = TOPICS_TELEGRAM["Tägliche Statistik"].get("id")
    if progress_report_thread_id is None:
         logging.error("❌ Не удалось найти thread_id для темы Tägliche Statistik для промежуточного отчета!")
         return


    conn = get_db_connection()
    cursor = conn.cursor()

    # 🔹 Получаем всех пользователей, которые писали в чат **за сегодня**
    cursor.execute("""
        SELECT DISTINCT user_id, username
        FROM messages_deepseek
        WHERE timestamp::date = CURRENT_DATE;
    """)
    all_users_today_interacted = {int(row[0]): row[1] for row in cursor.fetchall()}


    # 🔹 Собираем статистику по пользователям **за сегодня**
    cursor.execute("""
       WITH UserDailySentences AS (
            SELECT user_id, COUNT(DISTINCT id) AS total_assigned
            FROM daily_sentences_deepseek
            WHERE date = CURRENT_DATE
            GROUP BY user_id
       ),
       UserDailyTranslations AS (
            SELECT
                t.user_id,
                COUNT(DISTINCT t.id) AS translated_count,
                COALESCE(AVG(t.score), 0) AS avg_score
            FROM translations_deepseek t
            WHERE t.timestamp::date = CURRENT_DATE
            GROUP BY t.user_id
       ),
       UserDailyProgress AS (
            SELECT user_id,
                AVG(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS avg_time,
                SUM(EXTRACT(EPOCH FROM (end_time - start_time))/60) AS total_time
            FROM user_progress_deepseek
            WHERE completed = true AND start_time::date = CURRENT_DATE
            GROUP BY user_id
       )
       SELECT
            uds.user_id,
            COALESCE(uds.total_assigned, 0) AS total_sentences,
            COALESCE(udt.translated_count, 0) AS translated,
            GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) AS missed,
            COALESCE(udp.avg_time, 0) AS avg_time_minutes,
            COALESCE(udp.total_time, 0) AS total_time_minutes,
            COALESCE(udt.avg_score, 0) AS avg_score,
            COALESCE(udt.avg_score, 0)
            - (COALESCE(udp.avg_time, 0) * 2)
            - (GREATEST(0, COALESCE(uds.total_assigned, 0) - COALESCE(udt.translated_count, 0)) * 20) AS final_score
       FROM UserDailySentences uds
       LEFT JOIN UserDailyTranslations udt ON uds.user_id = udt.user_id
       LEFT JOIN UserDailyProgress udp ON uds.user_id = udp.user_id
       ORDER BY final_score DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    # 🔹 Identify users who had sentences assigned but didn't translate
    assigned_users_ids = {row[0] for row in rows}
    lazy_users_today = {uid: uname for uid, uname in all_users_today_interacted.items() if uid not in assigned_users_ids}


    # 🔹 Formulate the report
    if not rows and not lazy_users_today:
        # No assigned sentences AND no chat interaction today, maybe skip intermediate report?
        logging.info("📊 Нет данных для промежуточного отчета сегодня.")
        return

    current_time = datetime.now().strftime("%H:%M") # Shorter time format
    progress_report = f"📊 Промежуточные итоги перевода на {current_time}:\n\n"

    # Sort rows again by final score descending
    rows.sort(key=lambda x: x[-1], reverse=True)

    for user_id, total, translated, missed, avg_minutes, total_minutes, avg_score, final_score in rows:
        username = all_users_today_interacted.get(int(user_id), f'Неизвестный пользователь {user_id}') # Get username, fallback
        # Escape username for Markdown
        safe_username = escape_markdown(username)
        progress_report += (
            f"👤 {safe_username}\n"
            f"📜 Переведено: {translated}/{total}\n"
            f"🚨 Не переведено: {missed}\n"
            f"⏱ Время среднее: {avg_minutes:.1f} мин\n"
            f"⏱ Время общ.: {total_minutes:.1f} мин\n"
            f"🎯 Средняя оценка: {avg_score:.1f}/100\n"
            f"🏆 Итоговый балл: {final_score:.1f}\n\n"
        )

    # 🚨 **Добавляем блок про ленивых (писали в чат, но не переводили)**
    if lazy_users_today:
        progress_report += "\n🦥 Ленивцы (писали в чат сегодня, но не начали перевод):\n"
        for username in lazy_users_today.values():
            progress_report += f"👤 {escape_markdown(username)}: нет данных по переводу сегодня!\n"

    await context.bot.send_message(
        chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
        text=progress_report,
        message_thread_id=progress_report_thread_id, # ✅ Отправляем в топик Tägliche Statistik
        parse_mode = "Markdown" # Use Markdown
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
    count = cursor.rowcount
    cursor.close()
    conn.close()

    if count > 0:
         await context.bot.send_message(
             chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID,
             text=f"🔔 **Автоматически закрыто {count} незавершённых сессий за сегодня!**",
             message_thread_id=TOPICS_TELEGRAM["General"].get("id") # Send to General
             )
    else:
         logging.info("✅ Нет незавершенных сессий за сегодня для автоматического закрытия.")
         # Optionally send a message if no sessions were closed
         # await context.bot.send_message(chat_id=TEST_DEEPSEEK_BOT_GROUP_CHAT_ID, text="Сегодня не было незавершенных сессий для автоматического закрытия.", message_thread_id=TOPICS_TELEGRAM["General"].get("id"))


async def error_handler(update, context):
    """Log the error and send a telegram message to the user."""
    # Log the error before sending a message
    logger.error("Exception while handling an update:", exc_info=context.error)

    try:
        # Try to get the chat and thread ID where the error occurred
        chat_id = update.effective_chat.id if update and update.effective_chat else None
        message_thread_id = update.effective_message.message_thread_id if update and update.effective_message else None
        user_id = update.effective_user.id if update and update.effective_user else None

        # Create error message
        error_message = f"❌ Произошла ошибка при обработке запроса."
        if user_id:
             error_message += f" (Пользователь: {user_id})"
        error_message += "\nПопробуйте снова или обратитесь к администратору."

        # Send message to the user/chat/thread where it happened
        if chat_id:
             await context.bot.send_message(
                 chat_id=chat_id,
                 text=error_message,
                 message_thread_id=message_thread_id
                 )
        else:
             # If cannot determine chat_id, perhaps send to a predefined admin chat
             logging.error("❌ Не удалось отправить сообщение об ошибке пользователю, т.к. chat_id неизвестен.")

    except Exception as e:
        logger.error(f"❌ Exception while sending error message: {e}", exc_info=True)


async def main():
    # Initialize application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Initialize scheduler
    scheduler = AsyncIOScheduler()
    
    print("📌 Adding handlers...")
    # 🔹 Logging for all messages (group -1, non-blocking)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_message, block=False), group=-1)

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", user_stats))
    
    # Message handlers for user text input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message, block=False), group=1)
    
    # Reply keyboard button handlers
    application.add_handler(MessageHandler(filters.Text("📌 Выбрать тему") & ~filters.COMMAND, handle_reply_button_text), group=2)
    application.add_handler(MessageHandler(filters.Text("🚀 Начать перевод") & ~filters.COMMAND, handle_reply_button_text), group=2)
    application.add_handler(MessageHandler(filters.Text("📜 Проверить перевод") & ~filters.COMMAND, handle_reply_button_text), group=2)
    application.add_handler(MessageHandler(filters.Text("✅ Завершить перевод") & ~filters.COMMAND, handle_reply_button_text), group=2)
    application.add_handler(MessageHandler(filters.Text("🟡 Статистика") & ~filters.COMMAND, handle_reply_button_text), group=2)
    
    # Inline button handlers
    application.add_handler(CallbackQueryHandler(handle_button_click))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Set up scheduler jobs
    print("📌 Adding scheduler jobs...")
    
    # Morning reminders
    scheduler.add_job(
        send_morning_reminder, 
        "cron", 
        hour=6, 
        minute=30, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    # Other scheduled jobs
    scheduler.add_job(
        send_german_news, 
        "cron", 
        hour=6, 
        minute=45, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    scheduler.add_job(
        send_me_analytics_and_recommend_me, 
        "cron", 
        day_of_week="mon,wed", 
        hour=7, 
        minute=7, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    scheduler.add_job(
        force_finalize_sessions, 
        "cron", 
        hour=23, 
        minute=59, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    # Progress reports throughout the day
    for hour in [9, 14, 18]:
        scheduler.add_job(
            send_progress_report, 
            "cron", 
            hour=hour, 
            minute=5, 
            timezone='Europe/Berlin', 
            kwargs={'context': CallbackContext(application=application)}
        )
    
    # Daily summary
    scheduler.add_job(
        send_daily_summary, 
        "cron", 
        hour=22, 
        minute=45, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    # Weekly summary
    scheduler.add_job(
        send_weekly_summary, 
        "cron", 
        day_of_week="sun", 
        hour=22, 
        minute=55, 
        timezone='Europe/Berlin', 
        kwargs={'context': CallbackContext(application=application)}
    )
    
    # Initialize the application
    print("🔧 Initializing Telegram bot...")
    await application.initialize()
    print("✅ Bot initialized.")
    
    # Start the scheduler
    print("⚙️ Starting APScheduler...")
    scheduler.start()
    print("✅ APScheduler started.")
    
    # Start the bot
    print("🚀 Starting bot...")
    await application.start()
    print("✅ Bot started.")
    
    # Start polling
    print("📡 Starting polling...")
    await application.updater.start_polling(
        allowed_updates=[Update.MESSAGE.value, Update.CALLBACK_QUERY.value, Update.CHAT_MEMBER.value],
        drop_pending_updates=True
    )
    
    # Keep the application running
    print("🔄 Bot is running. Press Ctrl+C to stop.")
    
    # This will keep the coroutine running until it's interrupted
    try:
        # This creates a never-ending task that prevents the coroutine from exiting
        stopping_signal = asyncio.Future()
        await stopping_signal
    except asyncio.CancelledError:
        # Handle cancellation (e.g., KeyboardInterrupt)
        pass
    finally:
        # Clean shutdown
        print("🛑 Stopping bot and scheduler...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        scheduler.shutdown()
        print("✅ Bot and scheduler stopped.")

if __name__ == "__main__":
    try:
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Error in main: {e}")

# **Summary of Changes and Explanations:**

# 1.  **`start` function:**
#     *   Removed the commented-out line and added `message_thread_id = update.message.message_thread_id`.
#     *   Passed `message_thread_id=message_thread_id` to `context.bot.send_message`. When called inside a topic, this will be the topic's ID. When called in the main chat, it will be `None`, and Telegram handles sending to the main chat. This is the primary fix for the ReplyKeyboardMarkup not appearing in topics.

# 2.  **Scheduled Functions (`send_german_news`, `send_me_analytics_and_recommend_me`, `send_weekly_summary`, `send_daily_summary`, `send_progress_report`, `force_finalize_sessions`):**
#     *   Each function now retrieves the appropriate `thread_id` from `TOPICS_TELEGRAM` using `.get("id")` for safety.
#     *   It checks if the `thread_id` is `None` and logs an error if the topic ID is not found (this means the topic might not be created or the ID is wrong in the config).
#     *   The `thread_id` is passed to `context.bot.send_message`. This ensures news goes to the Nachrichten topic, different stats reports go to the Tägliche/Wöchenliche Statistik topics, recommendations go to Empfehlungen, and morning/final messages go to General.

# 3.  **`handle_button_click`:**
#     *   Corrected to only run if `update.callback_query` is present (it's registered as a `CallbackQueryHandler`).
#     *   Ensured `chat_id` and `message_thread_id` are correctly extracted from `query.message`.
#     *   Added a check if the clicked button (`query.data`) is allowed within the topic identified by `message_thread_id`. This prevents users from clicking "Start Translation" if the button somehow appears in the "News" topic, for example.
#     *   Added a fallback message and button removal if the button is not allowed or the topic is not found.
#     *   Clarified the `explain:` callback data handling, ensuring data is retrieved from `context.user_data` and passed to `check_translation_with_claude`. Changed the context key name slightly (`translation_for_claude_`) to be more specific.

# 4.  **`handle_user_message`:**
#     *   Added a check at the beginning to ignore messages starting with `/`, letting the `CommandHandler`s handle them.
#     *   Removed the incorrect call to `handle_button_click(update, context)` at the end. This function is only for processing text matching the numbered translation pattern.
#     *   Updated regex to handle multi-line translations slightly better and added error logging for unparseable lines.
#     *   Sent confirmation message back to the `message_thread_id` where the translation was sent.

# 5.  **`check_translation` and `check_translation_with_claude`:**
#     *   Ensured `target_thread_id` is correctly identified using `.get("id")` from `TOPICS_TELEGRAM`.
#     *   Added fallback logic to send messages to the effective thread ID (where the action originated) if the predefined topic ID is missing.
#     *   Updated `simulate_typing` and `edit_message_text` calls to use the correct `target_thread_id`.
#     *   Used `escape_markdown_v2` for message text and `parse_mode="MarkdownV2"` for better compatibility.
#     *   Added basic error handling for Telegram API errors during message editing.
#     *   Corrected logging of parsed data.

# 6.  **`log_translation_mistake`:**
#     *   Improved input validation and logging.
#     *   Enhanced logic to match normalized (lowercase) categories/subcategories against the validation lists.
#     *   Ensured original casing is restored when inserting into the database.
#     *   Added logging and rollback for database errors.

# 7.  **`check_user_translation`:**
#     *   Modified to accept the list of pending translations directly.
#     *   Added more robust parsing of the `pending_translations_list`.
#     *   Included checks to prevent double-checking translations for the same user and sentence on the same day.
#     *   Ensured `log_translation_mistake` is called correctly.

# 8.  **`get_original_sentences`:**
#     *   Slightly refined the logic to prioritize recent mistake sentences, then general ones, then GPT-generated ones, and shuffled the final list.
#     *   Added error handling and fallback if sentence retrieval/generation fails.

# 9.  **`search_youtube_videous`:**
#     *   Added `relevanceLanguage="de"` and `regionCode="DE"` to search queries for better German results.
#     *   Refined search logic to try preferred channels first, then broader search if not enough videos are found.
#     *   Used `escape_markdown_v2` for YouTube titles and URLs in the final Markdown links.

# 10. **`rate_mistakes`:**
#     *   Updated SQL query to count *unique* translated sentences per week.
#     *   Added calculation for *total sentences assigned* in the last week to correctly calculate *missed* sentences.
#     *   Refined the CTEs (Common Table Expressions) in the SQL to more correctly identify the top mistake category and subcategories based on counts in the last 7 days.
#     *   Added checks for NULL results from subqueries.

# 11. **`send_me_analytics_and_recommend_me`:**
#     *   Ensured the user list includes anyone with *any* activity (translations or mistakes) in the last week.
#     *   Only requests a topic from GPT if there were mistakes.
#     *   Used `escape_markdown_v2` for Markdown formatting.
#     *   Included the recommended topic in code block format.

# 12. **`send_daily_summary` and `send_progress_report`:**
#     *   Updated SQL queries to use more accurate CTEs (based on the weekly summary query structure) to calculate stats per user based on assigned sentences, translations, and progress entries *only for the current day*.
#     *   Identified "lazy" users as those who *interacted* (sent messages) today but had *no sentences assigned* (meaning they didn't start a session) today.
#     *   Used `escape_markdown` for usernames in summaries.

# 13. **`main` function:**
#     *   Registered specific `MessageHandler`s for the *text* of each button in `MAIN_MENU`. These point to `handle_reply_button_text`, which then calls the appropriate function.
#     *   Removed the incorrect `MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_click, block=False), group=1)`.
#     *   Switched from `BackgroundScheduler` to `AsyncIOScheduler` to allow scheduled jobs to directly use `await` and Telegram API calls without needing a helper `run_async_job` wrapper (which can sometimes cause event loop issues).
#     *   Added timezones to scheduled jobs (`timezone='Europe/Berlin'`).
#     *   Ensured `context=CallbackContext(application=application)` is passed to scheduled job functions where needed.
#     *   Refined `allowed_updates` in `application.run_polling` for better performance.

# These changes should address the ReplyKeyboardMarkup issue in topics and properly route your scheduled reports to the configured topic threads.Хорошо, давайте разберем новую ошибку:
