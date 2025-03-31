async def safe_send_message(context, chat_id, text, parse_mode=None, reply_markup=None):
    """
    Безопасная отправка сообщения с повторными попытками в случае ошибки Telegram API.
    """
    for attempt in range(3):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            logging.info(f"✅ Сообщение успешно отправлено в чат {chat_id}")
            return
        except TelegramError as e:
            logging.error(f"❌ Ошибка Telegram: {e}, попытка {attempt + 1}")
            if attempt == 2:
                logging.error(f"❌ Все попытки исчерпаны для чата {chat_id}, пропускаем.")
                return
            await asyncio.sleep(2 ** attempt)  # Задержка: 1, 2, 4 сек


# В коде нужно Замени вызовы context.bot.send_message на safe_send_message