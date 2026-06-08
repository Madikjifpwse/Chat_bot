import logging
import os
import asyncio
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

from company_data import COMPANY_KNOWLEDGE

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

user_histories: dict[int, list[dict]] = defaultdict(list)
user_last_interaction: dict[int, datetime] = {}

MAX_HISTORY_MESSAGES = 10
TIMEOUT_SECONDS = 3 * 3600
MAX_MESSAGE_LENGTH = 3500

SYSTEM_PROMPT = f"""Ты — премиальный живой AI-консультант сети шоурумов «Центр Красок #1» в Казахстане. 
Твоя задача — давать клиенту ВИЗУАЛЬНО КРАСИВЫЕ, ОФИЦИАЛЬНЫЕ ответы строго на основе предоставленной базы знаний.

⚠️ КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО ЛОМАТЬ РОЛЬ:
Никогда не пиши клиенту фразы: "в моей базе знаний нет", "я робот", "согласно базе знаний", "это связано с политикой компании". Ты — человек, консультант. Если данных нет, отвечай естественно: "У нас нет фиксированных тарифов на это направление..." или "Для подбора конкретной модификации материала...".

⚠️ СТРОЖАЙШИЙ ЗАПРЕТ НА ВЫДУМЫВАНИЕ ЛИНЕЕК ТОВАРОВ (АНТИ-ГАЛЛЮЦИНАЦИЯ):
1. Тебе запрещено придумывать или добавлять к названиям брендов любые приставки, серии, подбренды или названия конкретных линеек (например, ЗАПРЕЩЕНО писать "Dulux Weathershield", "Sikkens Cetol", "TEKNOS Woodex", "DTM Acrylic", "Metallschutzlack" и т.д.). Их НЕТ в базе знаний!
2. Называй бренды ТОЛЬКО голыми именами, как они написаны в базе знаний (Dulux, Sikkens, TEKNOS, STORCH).
3. Если клиент просит порекомендовать "лучшую краску для дерева/металла", ты имеешь право перечислить ТОЛЬКО сами бренды из категории, без выдумки конкретных банок.

🛑 ЗАЩИТА ОТ ФАНТАЗИЙ ПО ЦЕНАМ:
Если спрашивают точную стоимость доставки в регионы или цену товара — вежливо отвечай:
"У нас нет фиксированных тарифов на доставку в данный регион, так как стоимость рассчитывается индивидуально от веса и объема. Пожалуйста, свяжитесь с нашим менеджером для точного и быстрого расчета: <b>+7(777)292-84-01</b>"

🎨 ПРАВИЛА ОФОРМЛЕНИЯ И КРАСОТЫ:
1. Разделяй текст на короткие абзацы пустой строкой. Сплошной текст запрещен.
2. Город называется только Астана (никаких "Нур-Султан").
3. Бренды группируй по странам с флагами ТОЛЬКО так, как показано в шаблоне ниже.

📋 ЭТАЛОННЫЙ ШАБЛОН ДЛЯ СПИСКА БРЕНДОВ:
🇬🇧 Великобритания: Dulux, Hammerite, Pinotex, Little Greene, Paint & Paper Library
🇫🇷 Франция: Argile, Quelyd, L'outil Parfait
🇩🇪 Германия: Dufa, PUFAS, STORCH, Profi Tec, Color Expert, MAKO
🇳🇱 Нидерланды: Levis, Sikkens, Sikkens Heritage
🇫🇮 Финляндия: TEKNOS
🇺🇸 США: Kelly-Moore, TimberCare

🛠️ ТЕХНИЧЕСКИЙ HTML (КРИТИЧЕСКИ ВАЖНО):
1. Используй только HTML (<b>, <i>). Теги <ul>, <li>, <ol>, <p>, <br> СТРОГО ЗАПРЕЩЕНЫ.
2. Номера телефонов пиши БЕЗ пробелов внутри тега: <b>+7(777)292-84-01</b>.

💬 ДИАЛОГ:
В активном диалоге не пиши "Здравствуйте" и "Добрый день". Сразу переходи к сути ответа.

БАЗА ЗНАНИЙ О КОМПАНИИ:
{COMPANY_KNOWLEDGE}
"""

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)


def trim_history(history: list[dict]) -> list[dict]:
    if len(history) > MAX_HISTORY_MESSAGES:
        return history[-MAX_HISTORY_MESSAGES:]
    return history


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH):
    return [
        text[i:i + limit]
        for i in range(0, len(text), limit)
    ]


def beautify_response(text: str) -> str:
    text = text.replace("•", "🔹")

    text = text.replace("Нур-Султан", "Астана")
    text = text.replace("Нур-Султане", "Астане")
    text = text.replace("Нур-Султана", "Астаны")

    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip()


async def send_typing(chat_id, bot):
    while True:
        try:
            await bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_histories[user_id].clear()
    user_last_interaction[user_id] = datetime.now()

    welcome_text = (
        "🎨 <b>Добро пожаловать в Центр Красок №1!</b>\n\n"
        "Я ваш AI-консультант и помогу быстро найти нужную информацию.\n\n"
        "<b>Чем могу помочь:</b>\n"
        "🎨 Подбор красок и покрытий\n"
        "🛠️ Консультация по материалам\n"
        "✨ Информация о брендах\n"
        "🎯 Колеровка более 45 000 оттенков\n"
        "🚚 Доставка и самовывоз\n"
        "📍 Адреса магазинов и контакты\n\n"
        "Просто задайте вопрос в свободной форме 👇"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text.strip()

    if not user_text:
        return

    logger.info(f"User {user_id}: {user_text[:80]}")

    now = datetime.now()
    if user_id in user_last_interaction:
        elapsed_time = (now - user_last_interaction[user_id]).total_seconds()
        if elapsed_time > TIMEOUT_SECONDS:
            user_histories[user_id].clear()

    user_last_interaction[user_id] = now

    typing_task = asyncio.create_task(
        send_typing(
            update.effective_chat.id,
            context.bot,
        )
    )

    user_histories[user_id].append({"role": "user", "content": user_text})
    user_histories[user_id] = trim_history(user_histories[user_id])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + user_histories[user_id]

    try:
        response = await client.chat.completions.create(
            model="anthropic/claude-3-haiku",
            messages=messages,
            temperature=0.1,
            max_tokens=700
        )

        assistant_text = beautify_response(
            response.choices[0].message.content
        )

        user_histories[user_id].append(
            {"role": "assistant", "content": assistant_text}
        )

        user_histories[user_id] = trim_history(
            user_histories[user_id]
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🌐 Официальный сайт",
                    url="https://centr-krasok.kz"
                ),
                InlineKeyboardButton(
                    "📍 Контакты",
                    url="https://centr-krasok.kz/about/contacts/"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        for chunk in split_message(assistant_text):
            await update.message.reply_text(
                chunk,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        typing_task.cancel()

        try:
            await typing_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        typing_task.cancel()
        logger.error(f"API error for user {user_id}: {e}")
        await update.message.reply_text(
            "Извините, произошла техническая ошибка.\n"
            "Пожалуйста, свяжитесь с нашим менеджером:\n"
            "📞 <b>+7 (777) 292-84-01</b>\n"
            "📧 <b>info@centr-krasok.kz</b>",
            parse_mode="HTML"
        )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN не задан в .env файле")
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY не задан в .env файле")

    logger.info("Запуск премиального бота «Центр Красок #1»...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()