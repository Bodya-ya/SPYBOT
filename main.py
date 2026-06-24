import asyncio
from inspect import signature

import aiosqlite
import logging
import os
from os import getenv
from dotenv import load_dotenv
from datetime import datetime, timedelta
import html
from aiogram import Bot, Dispatcher, BaseMiddleware, types, F
from aiogram.types import (
    Update, BusinessConnection, BusinessMessagesDeleted, Message,
    Voice, VideoNote, PhotoSize, Document, Video, Audio, Sticker,
    FSInputFile, InputFile, InlineKeyboardMarkup, InlineKeyboardButton,LabeledPrice,PreCheckoutQuery
)
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command
import aiohttp

load_dotenv()

TOKEN = getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

bot = Bot(TOKEN)
dp = Dispatcher()

ADMIN_IDS = [911334605]

DB = "messages.db"
TEMP_DIR = "temp_files"  # Временная папка для скачивания

# Создаем временную папку если её нет
# Сразу после:
os.makedirs(TEMP_DIR, exist_ok=True)

# ⬇️ ВСТАВЬ ЭТОТ БЛОК СЮДА ⬇️
import json

USERS_FILE = "users.json"


def load_users():
    """Загружает список пользователей из JSON файла"""
    if not os.path.exists(USERS_FILE):
        return {"users": {}}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(data):
    """Сохраняет список пользователей в JSON файл"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_user(user_id, username=None, first_name=None, user_type="start"):
    """Добавляет или обновляет пользователя с указанием типа"""
    data = load_users()
    user_id_str = str(user_id)

    if user_id_str not in data["users"]:
        # Новый пользователь
        data["users"][user_id_str] = {
            "username": username,
            "first_name": first_name,
            "type": user_type,
            "joined_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "last_activity": datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        }
        logger.info(f"✅ Новый пользователь ({user_type}): {first_name} (@{username})")
    else:
        # Обновляем существующего
        data["users"][user_id_str]["username"] = username
        data["users"][user_id_str]["first_name"] = first_name
        # Если был start, а стал business — обновляем тип
        if user_type == "business":
            data["users"][user_id_str]["type"] = "business"
        data["users"][user_id_str]["last_activity"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    save_users(data)

def get_user(user_id):
    """Получает информацию о пользователе по ID"""
    data = load_users()
    return data["users"].get(str(user_id))


def get_all_users():
    """Получает всех пользователей"""
    data = load_users()
    return data["users"]

def get_users_by_type(user_type):
    """Получает пользователей по типу ('start' или 'business')"""
    data = load_users()
    return {uid: u for uid, u in data["users"].items() if u.get("type") == user_type}

def get_start_users():
    """Только те, кто нажал /start"""
    return get_users_by_type("start")

def get_business_users():
    """Только те, кто подключил бизнес-аккаунт"""
    return get_users_by_type("business")

def get_users_count():
    """Количество пользователей"""
    data = load_users()
    return len(data["users"])


def get_stats():
    """Статистика по типам пользователей"""
    data = load_users()
    total = len(data["users"])
    start_count = sum(1 for u in data["users"].values() if u.get("type") == "start")
    business_count = sum(1 for u in data["users"].values() if u.get("type") == "business")
    both_count = total - start_count - business_count  # Те, у кого другой тип

    return {
        "total": total,
        "start": start_count,
        "business": business_count
    }

CHANNEL_ID = "@eyelliz_life"  # Или -1001234567890 (цифровой ID)

async def check_channel_subscription(user_id: int) -> bool:
    """Проверяет, подписан ли пользователь на канал"""
    try:
        member = await bot.get_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id
        )
        # Подписан, если не "left" и не "kicked"
        return member.status not in ["left", "kicked"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False


# ⬆️ КОНЕЦ БЛОКА ⬆️

async def download_file(file_id, file_name=None):
    """Скачивает файл из Telegram во временную папку"""
    try:
        file = await bot.get_file(file_id)

        if not file_name:
            file_name = f"{file_id}.{file.file_path.split('.')[-1]}"

        file_path = os.path.join(TEMP_DIR, file_name)
        await bot.download_file(file.file_path, destination=file_path)

        return file_path
    except Exception as e:
        logger.error(f"Ошибка скачивания файла: {e}")
        return None


async def download_media(file_id, file_type):
    """Скачивает медиафайл"""
    try:
        file = await bot.get_file(file_id)
        ext = file.file_path.split('.')[-1] if '.' in file.file_path else 'bin'
        filename = f"{file_type}_{file.file_unique_id}.{ext}"
        filepath = os.path.join(TEMP_DIR, filename)
        await bot.download_file(file.file_path, destination=filepath)
        return filepath
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        return None

async def notify_owner_with_media(owner_id, text, file_id=None, file_type=None, caption=None):
    """
    Отправляет уведомление владельцу с медиафайлом
    """
    try:
        # Если есть файл и его тип, отправляем медиа
        if file_id and file_type:
            try:
                if file_type == "voice":
                    await bot.send_voice(chat_id=owner_id, voice=file_id, caption=text, parse_mode=ParseMode.HTML)
                elif file_type == "video_note":
                    await bot.send_message(chat_id=owner_id, text=text, parse_mode=ParseMode.HTML)
                    await bot.send_video_note(chat_id=owner_id, video_note=file_id)
                elif file_type == "photo":
                    await bot.send_photo(chat_id=owner_id, photo=file_id, caption=text, parse_mode=ParseMode.HTML)
                elif file_type == "video":
                    await bot.send_video(chat_id=owner_id, video=file_id, caption=text, parse_mode=ParseMode.HTML)
                elif file_type == "document":
                    await bot.send_document(chat_id=owner_id, document=file_id, caption=text, parse_mode=ParseMode.HTML)
                elif file_type == "audio":
                    await bot.send_audio(chat_id=owner_id, audio=file_id, caption=text, parse_mode=ParseMode.HTML)
                elif file_type == "sticker":
                    await bot.send_message(chat_id=owner_id, text=text, parse_mode=ParseMode.HTML)
                    await bot.send_sticker(chat_id=owner_id, sticker=file_id)
                elif file_type == "animation":
                    await bot.send_animation(chat_id=owner_id, animation=file_id, caption=text,
                                             parse_mode=ParseMode.HTML)
                else:
                    # Для текста и остального
                    await bot.send_message(chat_id=owner_id, text=text, parse_mode=ParseMode.HTML)

                logger.info(f"✅ Медиафайл отправлен: {file_type}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки медиа: {e}")
                # Если не удалось отправить медиа, отправляем только текст
                await bot.send_message(
                    chat_id=owner_id,
                    text=text + "\n\n⚠️ <i>Не удалось отправить медиафайл</i>",
                    parse_mode=ParseMode.HTML
                )
        else:
            # Если нет файла, отправляем только текст
            await bot.send_message(chat_id=owner_id, text=text, parse_mode=ParseMode.HTML)

        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки пользователю {owner_id}: {e}")
        return False

def get_message_type_info(message: Message):
    """Определяет тип сообщения и получает file_id"""

    username = f"@{message.from_user.username}" if message.from_user.username else None
    user_name = message.from_user.full_name or "Unknown"

    # Голосовое сообщение
    if message.voice:
        return {
            "message_type": "voice",
            "content": "Голосовое:",
            "file_id": message.voice.file_id,
            "caption": None,
            "user_name": user_name,  # ← Добавить
            "username": username  # ← Добавить
        }

    # Видеокружок
    elif message.video_note:
        return {
            "message_type": "video_note",
            "content" : "Видеосообщение:",
            "file_id": message.video_note.file_id,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Фото
    elif message.photo:
        largest_photo = message.photo[-1]
        size_mb = largest_photo.file_size / (1024 * 1024) if largest_photo.file_size else 0
        caption = message.caption or ""
        content = f"🌄 Фото:"
        return {
            "message_type": "photo",
            "content": content,
            "file_id": largest_photo.file_id,
            "caption": caption,
            "user_name": user_name,
            "username": username
        }

    # Документ
    elif message.document:
        file_name = message.document.file_name or "Без имени"
        size_mb = message.document.file_size / (1024 * 1024) if message.document.file_size else 0
        caption = message.caption or ""
        content = "📎 Документ:"
        return {
            "message_type": "document",
            "content": content,
            "file_id": message.document.file_id,
            "caption": message.caption,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Видео
    elif message.video:
        duration = message.video.duration
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
        size_mb = message.video.file_size / (1024 * 1024) if message.video.file_size else 0
        caption = message.caption or ""
        content = f"🎬 Видео:"
        return {
            "message_type": "video",
            "content": content,
            "file_id": message.video.file_id,
            "caption": message.caption,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Аудио
    elif message.audio:
        duration = message.audio.duration
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
        title = message.audio.title or "Без названия"
        performer = f" - {message.audio.performer}" if message.audio.performer else ""
        caption = message.caption or ""
        content = f"🎵 Аудио:"
        if caption:
            content += f"\nподпись:\n {caption}"
        return {
            "message_type": "audio",
            "content": content,
            "file_id": message.audio.file_id,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Стикер
    elif message.sticker:
        emoji = message.sticker.emoji or ""
        return {
            "message_type": "sticker",
            "content": "Стикер:",
            "file_id": message.sticker.file_id,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Анимация (GIF)
    elif message.animation:
        return {
            "message_type": "animation",
            "content": "🎞 Гифку",
            "file_id": message.animation.file_id,
            "caption": message.caption,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Местоположение
    elif message.location:
        lat = message.location.latitude
        lon = message.location.longitude
        return {
            "message_type": "location",
            "content": f"📍 Местоположение:: {lat}, {lon}",
            "file_id": None,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Контакт
    elif message.contact:
        name = message.contact.first_name
        phone = message.contact.phone_number
        return {
            "message_type": "contact",
            "content": f"👤 Контакт: {name} ({phone})",
            "file_id": None,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    # Опрос
    elif message.poll:
        question = message.poll.question
        return {
            "message_type": "poll",
            "content": f"📊 Опрос: {question}",
            "file_id": None,
            "caption": None,
            "user_name": user_name,
            "username": username  # ← Добавить# ← Добавить
        }

    elif message.text:
        return {
            "message_type": "text",
            "content": message.text,
            "file_id": None,
            "caption": None,
            "user_name": user_name,
            "username": username
        }
    else:
        return {
            "message_type": "other",
            "content": "📨 Сообщение (тип не определен)",
            "file_id": None,
            "caption": None,
            "user_name": user_name ,
            "username": username  # ← Добавить# ← Добавить
        }


async def init_db():
    """Инициализация БД с автоматической миграцией"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS business_connections (
            business_connection_id TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES owners(user_id)
        )
        """)

        cursor = await db.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='messages'
        """)
        table_exists = await cursor.fetchone()

        if not table_exists:
            await db.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_connection_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER,
                user_name TEXT,
                username TEXT,
                message_type TEXT DEFAULT 'text',
                content TEXT,
                file_id TEXT,
                caption TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_from_owner BOOLEAN DEFAULT FALSE,
                UNIQUE(business_connection_id, chat_id, message_id),
                FOREIGN KEY (business_connection_id) REFERENCES business_connections(business_connection_id)
            )
            """)
        else:
            cursor = await db.execute("PRAGMA table_info(messages)")
            columns = [row[1] for row in await cursor.fetchall()]

            # Добавляем недостающие колонки
            new_columns = {
                'user_name': 'TEXT',
                'is_from_owner': 'BOOLEAN DEFAULT FALSE',
                'message_type': "TEXT DEFAULT 'text'",
                'content': 'TEXT',
                'file_id': 'TEXT',
                'caption': 'TEXT',
                'username': 'TEXT',
                'chat_name': 'TEXT'
            }

            for col_name, col_type in new_columns.items():
                if col_name not in columns:
                    await db.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
                    logger.info(f"✅ Добавлена колонка {col_name}")

        # Индексы
        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_lookup 
        ON messages(message_id, chat_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_business 
        ON messages(business_connection_id)
        """)

        await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_type 
        ON messages(message_type)
        """)

        await db.commit()
        logger.info("✅ База данных готова")


async def register_owner(user_id, username=None, first_name=None):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT OR REPLACE INTO owners (user_id, username, first_name)
        VALUES (?, ?, ?)
        """, (user_id, username, first_name))
        await db.commit()


async def save_business_connection(business_connection_id, owner_id):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT OR REPLACE INTO business_connections (business_connection_id, owner_id)
        VALUES (?, ?)
        """, (business_connection_id, owner_id))
        await db.commit()


async def get_owner_by_business_connection(business_connection_id):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT owner_id FROM business_connections
            WHERE business_connection_id = ?
        """, (business_connection_id,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def save_message(data):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        INSERT OR REPLACE INTO messages
        (business_connection_id, message_id, chat_id, user_id, user_name, username, message_type, content, file_id, caption, is_from_owner, chat_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["business_connection_id"],
            data["message_id"],
            data["chat_id"],
            data["user_id"],
            data.get("user_name", "Unknown"),
            data.get("username"),  # Добавляем username
            data.get("message_type", "text"),
            data.get("content", ""),
            data.get("file_id"),
            data.get("caption"),
            data.get("is_from_owner", False),
            data.get("chat_name"),
        ))
        await db.commit()


async def save_payment(user_id, amount, currency, payload):
    """Сохраняет платеж. Подписку меняет только для не-донатов"""
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            currency TEXT,
            payload TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            active BOOLEAN DEFAULT TRUE,
            is_trial BOOLEAN DEFAULT FALSE
        )
        """)

        # Сохраняем платеж
        await db.execute("""
        INSERT INTO payments (user_id, amount, currency, payload)
        VALUES (?, ?, ?, ?)
        """, (user_id, amount, currency, payload))

        # ДОНАТ — просто сохраняем и выходим
        if "donate" in payload:
            await db.commit()
            return

        # ПОДПИСКА — меняем срок
        durations = {
            "chatguard_week": 7,
            "chatguard_month": 30
        }

        days = durations.get(payload)
        if days:
            expires_at = datetime.now() + timedelta(days=days)

            await db.execute("""
            INSERT OR REPLACE INTO subscriptions (user_id, plan, expires_at, active, is_trial)
            VALUES (?, ?, ?, TRUE, FALSE)
            """, (user_id, payload, expires_at.strftime("%Y-%m-%d %H:%M:%S")))

        await db.commit()


async def activate_trial(user_id):
    """Активирует пробный период на 7 дней"""
    async with aiosqlite.connect(DB) as db:
        # Создаем таблицу если нет
        await db.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            active BOOLEAN DEFAULT TRUE,
            is_trial BOOLEAN DEFAULT FALSE
        )
        """)

        # Проверяем колонку is_trial
        cursor = await db.execute("PRAGMA table_info(subscriptions)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'is_trial' not in columns:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN is_trial BOOLEAN DEFAULT FALSE")
            await db.commit()

        # Проверяем, был ли уже триал
        cursor = await db.execute("""
            SELECT COUNT(*) FROM subscriptions
            WHERE user_id = ? AND is_trial = TRUE
        """, (user_id,))
        had_trial = (await cursor.fetchone())[0] > 0

        if had_trial:
            return False

        expires_at = datetime.now() + timedelta(days=365)

        await db.execute("""
        INSERT OR REPLACE INTO subscriptions (user_id, plan, expires_at, active, is_trial)
        VALUES (?, 'trial', ?, TRUE, TRUE)
        """, (user_id, expires_at.strftime("%Y-%m-%d %H:%M:%S")))

        await db.commit()
        return True


async def check_subscription(user_id):
    """Проверяет активность подписки"""
    async with aiosqlite.connect(DB) as db:
        # Создаем таблицу если нет
        await db.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            plan TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            active BOOLEAN DEFAULT TRUE,
            is_trial BOOLEAN DEFAULT FALSE
        )
        """)

        cursor = await db.execute("PRAGMA table_info(subscriptions)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'is_trial' not in columns:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN is_trial BOOLEAN DEFAULT FALSE")
            await db.commit()

        cursor = await db.execute("""
            SELECT plan, expires_at, active, is_trial FROM subscriptions
            WHERE user_id = ? AND active = TRUE
            ORDER BY expires_at DESC
            LIMIT 1
        """, (user_id,))
        row = await cursor.fetchone()
        if not row:
            return None

        plan, expires_at_str, active, is_trial = row
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")

        if datetime.now() > expires_at:
            await db.execute("UPDATE subscriptions SET active = FALSE WHERE user_id = ?", (user_id,))
            await db.commit()
            return None

        days_left = (expires_at - datetime.now()).days

        return {
            "plan": plan,
            "expires_at": expires_at.strftime("%d.%m.%Y"),
            "days_left": days_left,
            "is_trial": is_trial
        }

def require_subscription(func):
    """Декоратор для проверки подписки"""

    async def wrapper(message: types.Message, *args, **kwargs):
        sub = await check_subscription(message.from_user.id)
        if not sub:
            await message.answer(
                "🔒 <b>Требуется подписка!</b>\n\n"
                "Для использования бота оплатите доступ.\n"
                "Используйте кнопку снизу для оплаты подписки.",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu()
            )
            return
        return await func(message, *args, **kwargs)

    return wrapper



async def get_message(message_id, chat_id):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("""
            SELECT user_id, user_name, username, content, created_at, is_from_owner, message_type, file_id, caption, business_connection_id, chat_name
            FROM messages
            WHERE message_id = ? AND chat_id = ?
        """, (message_id, chat_id))
        row = await cursor.fetchone()
        return row if row else None


async def cleanup_old_messages(days=7):
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        DELETE FROM messages 
        WHERE created_at < datetime('now', '-' || ? || ' days')
        """, (days,))
        await db.commit()


import html
from datetime import datetime, timedelta


def format_deleted_message(user_name, content, message_type="text", chat_id=None, created_at=None, user_id=None,
                           username=None, caption=None, is_owner=False, chat_name=None):
    time_str = ""
    signature = ""
    if created_at:
        try:
            dt = datetime.strptime(created_at.split('.')[0], "%Y-%m-%d %H:%M:%S")
            dt = dt + timedelta(hours=3)  # UTC+3 (Москва)
            time_str = f"🕐 {dt.strftime('%d.%m.%Y %H:%M')} (МСК)"
        except:
            pass

    type_icons = {
        "voice": "🎤",
        "video_note": "📹",
        "photo": "🖼",
        "document": "📎",
        "video": "🎬",
        "audio": "🎵",
        "sticker": "😀",
        "animation": "🎞",
        "location": "📍",
        "contact": "👤",
        "poll": "📊",
        "text": "💬"
    }

    icon = type_icons.get(message_type, "📨")

    # ЭКРАНИРУЕМ HTML спецсимволы
    safe_user_name = html.escape(user_name) if user_name else "Unknown"
    safe_content = html.escape(content) if content else ""
    safe_username = html.escape(username) if username else None
    safe_caption = html.escape(caption) if caption else None
    safe_chat_name = html.escape(chat_name) if chat_name else None

    # Формируем информацию о пользователе
    user_info = f"{safe_user_name}"
    if safe_username:
        user_info += f" ({safe_username})"
    user_info += "\n"

    if message_type == "text":
        content_part = f"💬 <b>Текст:</b>\n<blockquote>{safe_content}</blockquote>\n"
    else:
        # Для медиа — описание обычным текстом
        content_part = f"<b>{safe_content}</b>\n"

        # Подпись к медиа — в цитате (если есть)
        if safe_caption:
            signature = f"\n💬 <b>Подпись:</b>\n<blockquote>{safe_caption}</blockquote>\n"

    chat_info = f" в чате с @{safe_chat_name}" if safe_chat_name else ""

    if is_owner:
        header = f"<b>Удалено ваше сообщение{chat_info}</b>"
    else:
        header = f"<b>{user_info}удалил(а)</b>"

    return f"{header}\n\n{content_part}\n{signature}"


def format_edited_message(user_name, old_content, new_content, message_type="text", chat_id=None, user_id=None,
                          username=None, created_at=None):
    time_str = ""
    if created_at:
        try:
            dt = datetime.strptime(created_at.split('.')[0], "%Y-%m-%d %H:%M:%S")
            dt = dt + timedelta(hours=3)  # UTC+3 (Москва)
            time_str = f"🕐 {dt.strftime('%d.%m.%Y %H:%M')} (МСК)"
        except:
            pass
    type_icons = {
        "voice": "🎤",
        "video_note": "📹",
        "photo": "🖼",
        "document": "📎",
        "video": "🎬",
        "audio": "🎵",
        "sticker": "😀",
        "animation": "🎞",
        "location": "📍",
        "contact": "👤",
        "poll": "📊",
        "text": "💬"
    }

    icon = type_icons.get(message_type, "📨")

    # ЭКРАНИРУЕМ HTML
    safe_user_name = html.escape(user_name) if user_name else "Unknown"
    safe_username = html.escape(username) if username else None
    safe_old_content = html.escape(old_content) if old_content else ""
    safe_new_content = html.escape(new_content) if new_content else ""

    # Информация о пользователе
    user_info = f"👤 <b>От:</b> {safe_user_name}"
    if safe_username:
        user_info += f" ({safe_username})"
    user_info += "\n"

    old_quote = f"<blockquote>{safe_old_content}</blockquote>"
    new_quote = f"<blockquote>{safe_new_content}</blockquote>"

    return (
        f"✏️ <b>Пользователь изменил сообщение</b>\n\n"
        f"{user_info}"
        f"❌ <b>Было:</b>\n{old_quote}\n"
        f"✅ <b>Стало:</b>\n{new_quote}"
    )


def format_deleted_message_limited(user_name, message_type="text", chat_id=None):
    """Уведомление об удалении без показа содержимого"""

    type_icons = {
        "voice": "🎤",
        "video_note": "📹",
        "photo": "🖼",
        "document": "📎",
        "video": "🎬",
        "audio": "🎵",
        "sticker": "😀",
        "animation": "🎞",
        "location": "📍",
        "contact": "👤",
        "poll": "📊",
        "text": "💬"
    }

    icon = type_icons.get(message_type, "📨")
    safe_user_name = html.escape(user_name) if user_name else "Unknown"

    return (
        f"<b>{safe_user_name} удалил(а) сообщение</b>\n\n"
        f"{icon} Тип: {message_type}\n\n"
        f"🔒 <b>Содержимое скрыто</b>\n"
        f"<i>Оплатите подписку чтобы видеть удаленные сообщения</i>\n\n"
        f"💎 Используйте кнопку снизу для оплаты подписки."
    )


def format_edited_message_limited(user_name, message_type="text", chat_id=None):
    """Уведомление об изменении без показа содержимого"""

    type_icons = {
        "voice": "🎤",
        "video_note": "📹",
        "photo": "🖼",
        "document": "📎",
        "video": "🎬",
        "audio": "🎵",
        "sticker": "😀",
        "animation": "🎞",
        "location": "📍",
        "contact": "👤",
        "poll": "📊",
        "text": "💬"
    }

    icon = type_icons.get(message_type, "📨")
    safe_user_name = html.escape(user_name) if user_name else "Unknown"

    return (
        f"✏️ <b>{safe_user_name} изменил(а) сообщение</b>\n\n"
        f"{icon} Тип: {message_type}\n\n"
        f"🔒 <b>Содержимое скрыто</b>\n"
        f"<i>Оплатите подписку чтобы видеть изменения</i>\n\n"
        f"💎 /subscribe"
    )

# ---------------- ХЕНДЛЕРЫ ----------------
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Старт с проверкой подписки"""
    await register_owner(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    user = get_user(message.from_user.id)
    is_new = user is None  # Запоминаем ДО добавления

    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name, user_type="start")

    sub = await check_subscription(message.from_user.id)

    if not sub:
        trial_activated = await activate_trial(message.from_user.id)
        sub = await check_subscription(message.from_user.id)  # Обновляем sub

    # Новый пользователь
    if is_new:
        if sub and sub.get('is_trial'):
            await message.answer(
                    "👋 <b>Добро пожаловать в EyellizSPY!</b>\n\n"
                    "🎁 <b>Пробный период на 365 дней активирован!</b>\n\n"
                    f"📅 Действует до: {sub['expires_at']}\n"
                    "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                    "🔔 <b>Я буду присылать уведомления когда пользователи:</b>\n"
                    "• Удаляют любые сообщения\n"
                    "• ✏️ Изменяют сообщения\n\n"
                    "⚠️ После пробного периода потребуется оплата.\n"
                    "💡 Используйте кнопку снизу для управления подпиской",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu(),
                )
        else:
            await message.answer(
                    "👋 <b>Добро пожаловать в EyellizSPY!</b>\n\n"
                    "🔒 <b>Пробный период уже использован.</b>\n\n"
                    "Для продолжения оплатите подписку.\n"
                    "💡 Используйте кнопку снизу для управления подпиской",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu(),
            )

        # Видео показываем всегда новым пользователям
        await message.answer_animation(
            animation="CgACAgIAAxkBAAMHaimoqXWpQb2nwLJEVT4WV5RVY84AAn6hAAIbTkBJaHaIC85dOnU7BA",
            caption="📹Исключительно на новых версиях официального приложения Telegram.\n\n"
                    "В случае отсутствия новой версии: Настройки -> Telegram для бизнеса -> Чат-боты :\n"
                    "Ввести тег бота - @EyellizSPY_BOT"
        )

    # Существующий пользователь
    else:
        if sub:
            trial_text = "🎁 Пробный период" if sub.get('is_trial') else "✅ Подписка активна"
            await message.answer(
                f"👋 Привет, {html.escape(message.from_user.first_name)}!\n\n"
                f"{trial_text}\n"
                f"📅 Действует до: {sub['expires_at']}\n"
                f"📆 Осталось дней: {sub['days_left']}\n\n"
                "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                reply_markup=startmenu(),
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer(
                f"👋 Привет, {html.escape(message.from_user.first_name)}!\n\n"
                f"🔒 <b>Подписка не активна</b>\n\n"
                f"Оплатите доступ для использования бота.\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                reply_markup=startmenu(),
                parse_mode=ParseMode.HTML
            )

@dp.message(Command("start"))
async def start_handler_after_tgk(message: types.Message):
    await register_owner(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    user = get_user(message.from_user.id)
    is_new = user is None  # Запоминаем ДО добавления

    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name, user_type="start")

    sub = await check_subscription(message.from_user.id)

    if not sub:
        trial_activated = await activate_trial(message.from_user.id)
        sub = await check_subscription(message.from_user.id)  # Обновляем sub

    # Новый пользователь
    if is_new:
        if sub and sub.get('is_trial'):
            await message.answer(
                "👋 <b>Добро пожаловать в EyellizSPY!</b>\n\n"
                "🎁 <b>Пробный период на 365 дней активирован!</b>\n\n"
                f"📅 Действует до: {sub['expires_at']}\n"
                "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                "🔔 <b>Я буду присылать уведомления когда пользователи:</b>\n"
                "• Удаляют любые сообщения\n"
                "• ✏️ Изменяют сообщения\n\n"
                "⚠️ После пробного периода потребуется оплата.\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu(),
            )
        else:
            await message.answer(
                "👋 <b>Добро пожаловать в EyellizSPY!</b>\n\n"
                "🔒 <b>Пробный период уже использован.</b>\n\n"
                "Для продолжения оплатите подписку.\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu(),
            )

    # Существующий пользователь
    else:
        if sub:
            trial_text = "🎁 Пробный период" if sub.get('is_trial') else "✅ Подписка активна"
            await message.answer(
                f"👋 Привет, {html.escape(message.from_user.first_name)}!\n\n"
                f"{trial_text}\n"
                f"📅 Действует до: {sub['expires_at']}\n"
                f"📆 Осталось дней: {sub['days_left']}\n\n"
                "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                reply_markup=startmenu(),
                parse_mode=ParseMode.HTML
            )
        else:
            await message.answer(
                f"👋 Привет, {html.escape(message.from_user.first_name)}!\n\n"
                f"🔒 <b>Подписка не активна</b>\n\n"
                f"Оплатите доступ для использования бота.\n"
                "💡 Используйте кнопку снизу для управления подпиской",
                reply_markup=startmenu(),
                parse_mode=ParseMode.HTML
            )

@dp.business_connection()
async def handle_business_connection(business_connection: BusinessConnection):
    owner_id = business_connection.user.id

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://t.me/eyelliz_life")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

    # Проверяем подписку на канал
    is_subscribed = await check_channel_subscription(owner_id)

    if not is_subscribed:
        await bot.send_message(
            chat_id=owner_id,
            text="📢 <b>Требуется подписка на канал!</b>\n\n"
                 "Подпишитесь на @eyelliz_life, затем нажмите кнопку проверки.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        return

    owner_id = business_connection.user.id

    is_enabled = business_connection.is_enabled

    sub = await check_subscription(owner_id)
    if is_enabled:
        # Подключение бота
        await register_owner(
            owner_id,
            business_connection.user.username,
            business_connection.user.first_name
        )
        add_user(
            user_id=owner_id,
            username=business_connection.user.username,
            first_name=business_connection.user.first_name,
            user_type="business"
        )

        await save_business_connection(business_connection.id, owner_id)

        logger.info(f"🔗 Бизнес-аккаунт подключен: {business_connection.user.first_name}")

        # Проверяем подписку
        sub = await check_subscription(owner_id)

        if not sub:
            trial_activated = await activate_trial(owner_id)

            if trial_activated:
                await bot.send_message(
                    chat_id=owner_id,
                    text="✅ <b>Бизнес-аккаунт успешно подключен!</b>\n\n"
                         "🎁 <b>Вам активирован пробный период на 365 дней!</b>\n\n"
                         "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                         "Теперь вы будете получать уведомления о всех удаленных и измененных сообщениях.\n"
                         "При удалении медиафайлов - я отправлю их вам!\n\n"
                         "⚠️ <i>После пробного периода потребуется оплата.</i>\n"
                         "💡 Используйте кнопку снизу для управления подпиской",
                    parse_mode=ParseMode.HTML,
                    reply_markup=startmenu()
                )
            else:
                await bot.send_message(
                    chat_id=owner_id,
                    text="✅ <b>Бизнес-аккаунт успешно подключен!</b>\n\n"
                         "🔒 <b>Пробный период уже был использован.</b>\n\n"
                         "Для продолжения использования оплатите подписку.\n"
                         "💡 Используйте кнопку снизу для управления подпиской",
                    parse_mode=ParseMode.HTML,
                    reply_markup=startmenu()
                )
        else:
            trial_text = "🎁 Пробный период" if sub.get('is_trial') else "✅ Подписка активна"

            await bot.send_message(
                chat_id=owner_id,
                text=f"✅ <b>Бизнес-аккаунт успешно подключен!</b>\n\n"
                     f"{trial_text}\n"
                     f"📅 Действует до: {sub['expires_at']}\n"
                     f"📆 Осталось дней: {sub['days_left']}\n\n"
                     "(В дальнейшем будет выпущена версия с платным доступом, однако в ближайшее время бот предоставляется бесплатно.)\n\n"
                     f"Вы будете получать уведомления о всех удаленных и измененных сообщениях.\n"
                     f"При удалении медиафайлов - я отправлю их вам!",
                parse_mode=ParseMode.HTML,
                reply_markup=startmenu()
            )
    else:
        # Отключение бота
        logger.info(f"🔌 Бизнес-аккаунт отключен: {business_connection.user.first_name}")

        # Можно удалить связь из БД
        async with aiosqlite.connect(DB) as db:
            await db.execute("""
                    DELETE FROM business_connections 
                    WHERE business_connection_id = ?
                    """, (business_connection.id,))
            await db.commit()

        # Отправляем прощальное сообщение
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Как подключить снова", callback_data="how_to_connect")],
            [InlineKeyboardButton(text="Помощь", url="t.me/m/X9EGMufdYmVi")]
        ])

        add_user(
            user_id=owner_id,
            username=business_connection.user.username,
            first_name=business_connection.user.first_name,
            user_type="start"  # ← Обратно в start
        )

        await bot.send_message(
            chat_id=owner_id,
            text="🔌 <b>Бизнес-аккаунт отключен.</b>\n\n"
                 "Вы больше не будете получать уведомления.\n"
                 "Чтобы снова подключить бота, перейдите в настройки Telegram Business.",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )


@dp.callback_query(lambda c: c.data == "check_subscription")
async def check_subscription_callback(callback: types.CallbackQuery):
    """Проверка подписки по кнопке"""
    is_subscribed = await check_channel_subscription(callback.from_user.id)

    if is_subscribed:
        await callback.message.delete()
        await callback.message.answer("✅ Спасибо за подписку!")
        # Повторно вызываем start
        await start_handler_after_tgk(callback.message)
    else:
        await callback.answer("❌ Вы ещё не подписались!", show_alert=True)

@dp.business_message()
async def handle_business_message(message: Message):
    owner_id = await get_owner_by_business_connection(message.business_connection_id)
    if not owner_id:
        return
    if message.chat.title:
        chat_name = message.chat.title
    else:
        # Личный чат — username чата (собеседника)
        if message.chat.username:
            chat_name = f"{message.chat.username}"
        else:
            chat_name = message.chat.first_name or message.chat.full_name or f"Чат {message.chat.id}"
    msg_info = get_message_type_info(message)
    is_from_owner = (message.from_user.id == owner_id)

    await save_message({
        "business_connection_id": message.business_connection_id,
        "message_id": message.message_id,
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "user_name": msg_info.get("user_name", "Unknown"),
        "username": msg_info.get("username"),
        "message_type": msg_info.get("message_type", "text"),
        "content": msg_info.get("content", ""),
        "file_id": msg_info.get("file_id"),
        "caption": msg_info.get("caption"),
        "is_from_owner": is_from_owner,
        "chat_name": chat_name,
    })
    if is_from_owner and message.reply_to_message:
        replied_msg = message.reply_to_message
        saved = await get_message(replied_msg.message_id, message.chat.id)

        if not saved and (replied_msg.photo or replied_msg.video or replied_msg.voice or replied_msg.video_note):
            # Определяем file_id
            if replied_msg.photo:
                file_id = replied_msg.photo[-1].file_id
                file_type = "photo"
            elif replied_msg.video:
                file_id = replied_msg.video.file_id
                file_type = "video"
            elif replied_msg.voice:
                file_id = replied_msg.voice.file_id
                file_type = "voice"
            elif replied_msg.video_note:
                file_id = replied_msg.video_note.file_id
                file_type = "video_note"
            else:
                file_id = None
                file_type = None

            if file_id:
                # Скачиваем файл
                local_path = await download_media(file_id, file_type)

                if local_path:
                    # Сохраняем в БД с локальным путём
                    await save_message({
                        "business_connection_id": message.business_connection_id,
                        "message_id": replied_msg.message_id,
                        "chat_id": message.chat.id,
                        "user_id": replied_msg.from_user.id,
                        "user_name": replied_msg.from_user.full_name or "Unknown",
                        "username": f"@{replied_msg.from_user.username}" if replied_msg.from_user.username else None,
                        "message_type": file_type,
                        "content": f"{file_type} (сохранено)",
                        "file_id": file_id,
                        "local_path": local_path,
                        "caption": replied_msg.caption,
                        "is_from_owner": False,
                        "chat_name": chat_name
                    })

                    # Отправляем владельцу
                    from aiogram.types import FSInputFile
                    file = FSInputFile(local_path)

                    if file_type == "photo":
                        await bot.send_photo(owner_id, file, caption=f"🌄 Одноразовая фотография из чата с @{chat_name}")
                    elif file_type == "video":
                        await bot.send_video(owner_id, file, caption=f"🎬 Одноразовое видео из чата с @{chat_name}")
                    elif file_type == "voice":
                        await bot.send_voice(owner_id, file, caption=f"🎙 Одноразовое голосовое из чата с @{chat_name}")
                    elif file_type == "video_note":
                        await bot.send_message(owner_id, f"Одноразовое видеосообщение из чата с @{chat_name}")
                        await bot.send_video_note(owner_id, file)

                    try:
                        os.remove(local_path)
                        print(f"🗑 Файл удалён: {local_path}")
                    except Exception as e:
                        print(f"Ошибка удаления: {e}")


@dp.edited_business_message()
async def handle_edited_business_message(message: Message):
    bcid = message.business_connection_id
    chat_id = message.chat.id

    owner_id = await get_owner_by_business_connection(bcid)
    if not owner_id:
        return

    old_data = await get_message(message.message_id, chat_id)
    if not old_data:
        return

    # Добавь username в распаковку
    user_id, user_name, username, old_content, created_at, is_from_owner, old_type, old_file_id, old_caption, _ = old_data

    if not is_from_owner:
        new_info = get_message_type_info(message)

        await save_message({
            "business_connection_id": bcid,
            "message_id": message.message_id,
            "chat_id": chat_id,
            "user_id": message.from_user.id,
            "user_name": new_info.get("user_name", user_name),
            "username": new_info.get("username", username),
            "message_type": new_info.get("message_type", old_type),
            "content": new_info.get("content", ""),
            "file_id": new_info.get("file_id", old_file_id),
            "caption": new_info.get("caption", old_caption),
            "is_from_owner": False
        })

        sub = await check_subscription(owner_id)

        if sub:
            # Полный доступ — показываем что изменили
            notification = format_edited_message(
                user_name, old_content, new_info["content"],
                old_type, chat_id, user_id, username
            )
            await notify_owner_with_media(owner_id, notification, new_info["file_id"], new_info["message_type"],
                                          new_info["caption"])
        else:
            notification = format_edited_message_limited(
                user_name, old_type, chat_id
            )
        await notify_owner_with_media(owner_id, notification, None, "text", None)


@dp.deleted_business_messages()
async def handle_deleted_business_messages(deleted_messages: BusinessMessagesDeleted):
    bcid = deleted_messages.business_connection_id
    chat_id = deleted_messages.chat.id
    print(f"🗑 DELETED: {deleted_messages.message_ids}")
    print(f"🗑 bcid: {bcid}")
    print(f"🗑 chat_id: {chat_id}")
    owner_id = await get_owner_by_business_connection(bcid)
    print(f"🗑 owner_id: {owner_id}")
    if not owner_id:
        print("🗑 НЕТ ВЛАДЕЛЬЦА — выход")
        return

    sub = await check_subscription(owner_id)
    print(f"🗑 sub: {sub}")

    for msg_id in deleted_messages.message_ids:
        msg_data = await get_message(msg_id, chat_id)
        print(f"🗑 msg_data: {msg_data}")

        if msg_data:
            user_id, user_name, username, content, created_at, is_from_owner, msg_type, file_id, caption, _, chat_name = msg_data
            print(f"🗑 is_from_owner: {msg_data[5]}")
            if sub:
                notification = format_deleted_message(
                    user_name=user_name,
                    content=content,
                    message_type=msg_type,
                    chat_id=chat_id,
                    created_at=created_at,
                    user_id=user_id,
                    username=username,
                    caption=caption,
                    is_owner=is_from_owner,
                    chat_name=chat_name  # ← ДОБАВИЛ
                )
                await notify_owner_with_media(owner_id, notification, file_id, msg_type, caption)
            else:
                print("🗑 СООБЩЕНИЕ НЕ НАЙДЕНО В БД!")
                notification = format_deleted_message_limited(user_name, msg_type, chat_id)
                await bot.send_message(
                    chat_id=owner_id,
                    text=notification,
                    reply_markup=startmenu(),
                    parse_mode=ParseMode.HTML
                )




@dp.message(Command("test"))
async def test_trial(message: types.Message):
    """Тест триала"""
    # Удаляем старые записи
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id = ?", (message.from_user.id,))
        await db.commit()

    # Пробуем активировать
    result = await activate_trial(message.from_user.id)
    await message.answer(f"Триал: {result}")

    # Проверяем
    sub = await check_subscription(message.from_user.id)
    await message.answer(f"Подписка: {sub}")

def get_admin_keyboard():
    buttons = [
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_users_all")],
        [InlineKeyboardButton(text="🚀 Бизнес-пользователи", callback_data="admin_users_business")],
        [InlineKeyboardButton(text="👋 Start пользователи", callback_data="admin_users_start")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard():
    buttons = [
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(lambda c: c.data == "how_to_connect")
async def disconect(callback: types.CallbackQuery):
    await callback.message.answer_animation(
        animation="CgACAgIAAxkBAAMHaimoqXWpQb2nwLJEVT4WV5RVY84AAn6hAAIbTkBJaHaIC85dOnU7BA",
        caption="📹Исключительно на новых версиях официального приложения Telegram.\n\n"
                "В случае отсутствия новой версии: Настройки -> Telegram для бизнеса -> Чат-боты :\n"
                "Ввести тег бота - @EyellizSPY_BOT"
    )

async def show_users_list(callback, users, title):
    sub = await check_subscription(callback.from_user.id)
    """Показывает список пользователей"""
    if not users:
        await callback.message.edit_text(
            f"<b>{title}</b>\n\nПока ни одного пользователя",
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    users_list = list(users.items())

    text = f"<b>{title} ({len(users_list)}):</b>\n\n"

    for user_id, user_data in users_list:
        # ЭКРАНИРУЕМ HTML!
        name = html.escape(user_data.get("first_name", "Без имени"))
        username = user_data.get("username")
        safe_username = f"(@{html.escape(username)})" if username else ""
        user_type = "🚀 Бизнес" if user_data.get("type") == "business" else "👋 Старт"
        joined = user_data.get("joined_at", "Неизвестно")

        text += f"🆔 <code>{user_id}</code>\n"
        text += f"👤 {name} {safe_username}\n"
        text += f"📌 {user_type}\n"
        text += f"📅 {joined}\n\n"
        text += f"📆 Осталось дней: {sub['days_left']}"

    await callback.message.edit_text(
        text,
        reply_markup=get_back_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


def get_subscribe_keyboard():
    buttons = [
        # [InlineKeyboardButton(text="⭐ Неделя - 35 звезд", callback_data="sub_week")],
        # [InlineKeyboardButton(text="⭐ Месяц - 75 звезд", callback_data="sub_month")],
        [InlineKeyboardButton(text="📊 Проверить статус подписки", callback_data="check_sub")],
        [InlineKeyboardButton(text="💝 Донат", callback_data="sub_donate")],
        # [InlineKeyboardButton(text="💳 Способы оплаты", callback_data="sub_info")],
        [InlineKeyboardButton(text="Помощь", url="t.me/m/X9EGMufdYmVi")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_keyboard():
    """Клавиатура для выбора оплаты"""
    buttons = [
        [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="pay_stars")],
        [InlineKeyboardButton(text="💳СБП (Скоро...)", callback_data="")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscribe")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def startmenu():
    buttons = [
        [InlineKeyboardButton(text="Приобрести подписку!", callback_data="back_to_subscribe")],
        [InlineKeyboardButton(text="Помощь", url="t.me/m/X9EGMufdYmVi")]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)




@dp.callback_query(lambda c: c.data == "sub_week")
async def sub_week_handler(callback: types.CallbackQuery):
    """Оплата за неделю"""
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="EyellizSPY — Неделя",
        description="Доступ к боту на 7 дней",
        payload="EyellizSPY_week",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Неделя доступа", amount=35)],
        start_parameter="sub_week",
        need_name=False,
        need_phone_number=False,
        need_email=False
    )
    await callback.answer("✅ Счет отправлен!")


@dp.callback_query(lambda c: c.data == "sub_month")
async def sub_month_handler(callback: types.CallbackQuery):
    """Оплата за месяц"""
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="EyellizSPY — Месяц",
        description="Доступ к боту на 30 дней",
        payload="EyellizSPY_month",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Месяц доступа", amount=75)],
        start_parameter="sub_month",
        need_name=False,
        need_phone_number=False,
        need_email=False
    )
    await callback.answer("✅ Счет отправлен!")


@dp.callback_query(lambda c: c.data == "sub_donate")
async def sub_donate_handler(callback: types.CallbackQuery):
    """Донат"""
    # Создаем кнопки с разными суммами доната
    donate_buttons = [
        [InlineKeyboardButton(text="💝 1 ⭐", callback_data="donate_1")],
        [InlineKeyboardButton(text="💝 5 ⭐", callback_data="donate_5")],
        [InlineKeyboardButton(text="💝 15 ⭐", callback_data="donate_15")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscribe")]
    ]

    await callback.message.edit_text(
        "💝 <b>Поддержать проект</b>\n\n"
        "Выберите сумму доната:\n\n"
        "Спасибо за вашу поддержку! ❤️",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=donate_buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("donate_"))
async def donate_amount_handler(callback: types.CallbackQuery):
    """Обработка выбора суммы доната"""
    amount = int(callback.data.split("_")[1])

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Поддержка EyellizSPY",
        description="Спасибо за поддержку проекта!",
        payload=f"EyellizSPY_donate_{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Донат", amount=amount)],
        start_parameter=f"donate_{amount}",
        need_name=False,
        need_phone_number=False,
        need_email=False
    )
    await callback.answer("✅ Счет отправлен!")


@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    """Проверка статуса подписки"""
    sub = await check_subscription(callback.from_user.id)

    from datetime import datetime
    now = datetime.now().strftime("%H:%M:%S")

    if sub:
        plan_names = {
            "trial": "🎁 Пробный период",
            "EyellizSPY_week": "📅 Неделя",
            "EyellizSPY_month": "📅 Месяц"
        }
        plan_name = plan_names.get(sub['plan'], sub['plan'])

        await callback.message.edit_text(
            f"✅ <b>Подписка активна!</b>\n\n"
            f"📋 План: {plan_name}\n"
            f"⏳ Действует до: {sub['expires_at']}\n"
            f"📆 Осталось дней: {sub['days_left']}\n\n"
            f"Спасибо, что вы с нами! 🎉\n"
            f"<i>Обновлено: {now}</i>",
            reply_markup=get_subscribe_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        await callback.message.edit_text(
            "❌ <b>Подписка не активна</b>\n\n"
            "Выберите тариф для оплаты.",
            reply_markup=get_subscribe_keyboard(),
            parse_mode=ParseMode.HTML
        )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "sub_info")
async def sub_info_handler(callback: types.CallbackQuery):
    """Информация о способах оплаты"""
    await callback.message.edit_text(
        "💳 <b>Способы оплаты:</b>\n\n"
        "⭐ <b>Telegram Stars</b>\n"
        "• Встроенная валюта Telegram\n"
        "• Покупаются в приложении\n"
        "• Мгновенная оплата\n\n"
        "💳<b>СБП</b>\n"
        "(В скором времени будет добавлено.)\n\n"
        "💎 <b>Зачем нужна подписка:</b>\n"
        "• Отслеживание удаленных сообщений\n"
        "• Сохранение медиафайлов\n"
        "• История изменений",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_subscribe")]
        ]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_subscribe")
async def back_to_subscribe_handler(callback: types.CallbackQuery):
    """Возврат в меню подписки"""
    sub = await check_subscription(callback.from_user.id)

    if sub:
        plan_names = {
            "trial": "🎁 Пробный период",
            "EyellizSPY_week": "📅 Неделя",
            "EyellizSPY_month": "📅 Месяц"
        }
        plan_name = plan_names.get(sub['plan'], sub['plan'])

        status_text = (
            f"✅ <b>Подписка активна!</b>\n\n"
            f"📋 План: {plan_name}\n"
            f"⏳ Действует до: {sub['expires_at']}\n"
            f"📆 Осталось дней: {sub['days_left']}\n\n"
            f"<i>Вы можете продлить подписку</i>"
        )
    else:
        status_text = (
            f"💎 <b>EyellizSPY Premium</b>\n\n"
            f"Выберите тариф:\n\n"
            # f"📅 Неделя — 35 ⭐\n"
            # f"📅 Месяц — 75 ⭐\n\n"
            f"💝 Донат — поддержать проект\n\n"
            f"<i>Оплата через Telegram Stars</i>"
        )

    await callback.message.edit_text(
        status_text,
        reply_markup=get_subscribe_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ============ УСПЕШНАЯ ОПЛАТА ============

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payment = message.successful_payment

    await save_payment(
        user_id=message.from_user.id,
        amount=payment.total_amount,
        currency=payment.currency,
        payload=payment.invoice_payload
    )

    sub = await check_subscription(message.from_user.id)

    if "donate" in payment.invoice_payload:
        await message.answer(
            f"💝 <b>Спасибо за донат!</b>\n\n"
            f"⭐ Сумма: {payment.total_amount} звезд\n\n"
            f"Ваша поддержка помогает проекту развиваться! ❤️",
            reply_markup=get_subscribe_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        plan_names = {
            "EyellizSPY_week": "📅 Неделя",
            "EyellizSPY_month": "📅 Месяц"
        }
        plan_name = plan_names.get(payment.invoice_payload, "Подписка")

        await message.answer(
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"📋 План: {plan_name}\n"
            f"⭐ Сумма: {payment.total_amount} звезд\n"
            f"📅 Действует до: {sub['expires_at']}\n"
            f"📆 Дней: {sub['days_left']}\n\n"
            f"Спасибо, что выбрали EyellizSPY! 🎉",
            reply_markup=get_subscribe_keyboard(),
            parse_mode=ParseMode.HTML
        )

# ============ ЗАЩИТА ХЕНДЛЕРОВ ============
# Оборачиваешь хендлеры, которые требуют подписку:


# ============ ХЕНДЛЕРЫ АДМИНКИ ============
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return

    await message.answer(
        "🔐 <b>Админ-панель EyellizSPY</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )


@dp.callback_query(lambda c: c.data == "admin_back")
async def back_to_admin(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🔐 <b>Админ-панель EyellizSPY</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_users_all")
async def show_all_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await show_users_list(callback, get_all_users(), "👥 Все пользователи")


@dp.callback_query(lambda c: c.data == "admin_users_business")
async def show_business_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await show_users_list(callback, get_business_users(), "🚀 Бизнес-пользователи")


@dp.callback_query(lambda c: c.data == "admin_users_start")
async def show_start_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await show_users_list(callback, get_start_users(), "👋 Start пользователи")


@dp.callback_query(lambda c: c.data == "admin_stats")
async def show_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    stats = get_stats()

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM business_connections")
        total_connections = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM messages")
        total_messages = (await cursor.fetchone())[0]

    text = "📊 <b>Статистика:</b>\n\n"
    text += f"👥 Всего: {stats['total']}\n"
    text += f"🚀 Бизнес: {stats['business']}\n"
    text += f"👋 Старт: {stats['start']}\n"
    text += f"🔗 Подключений: {total_connections}\n"
    text += f"💬 Сообщений: {total_messages}\n"

    await callback.message.edit_text(text, reply_markup=get_back_keyboard(), parse_mode=ParseMode.HTML)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_refresh")
async def refresh_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return

    stats = get_stats()

    # Добавляем время обновления чтобы текст всегда был разным
    from datetime import datetime
    now = datetime.now().strftime("%H:%M:%S")

    await callback.message.edit_text(
        f"🔐 <b>Админ-панель EyellizSPY</b>\n\n"
        f"👥 Пользователей: {stats['total']}\n"
        f"🚀 Бизнес: {stats['business']}\n"
        f"👋 Старт: {stats['start']}\n\n"
        f"Выберите действие:\n"
        f"<i>Обновлено: {now}</i>",  # ← Всегда разный текст
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer("✅ Обновлено!")
# ---------------- ОЧИСТКА ВРЕМЕННЫХ ФАЙЛОВ ----------------
async def cleanup_temp_files():
    """Очищает временные файлы старше 1 часа"""
    while True:
        await asyncio.sleep(1800)  # Каждый час
        try:
            now = datetime.now().timestamp()
            for filename in os.listdir(TEMP_DIR):
                filepath = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 1800:  # Старше часа
                        os.remove(filepath)
                        logger.info(f"Удален временный файл: {filename}")
        except Exception as e:
            logger.error(f"Ошибка очистки временных файлов: {e}")


async def periodic_cleanup():
    """Периодически очищает старые сообщения из БД"""
    while True:
        await asyncio.sleep(86400)
        await cleanup_old_messages(7)
        logger.info("🧹 Выполнена очистка старых сообщений")


# ---------------- ЗАПУСК ----------------
async def main():
    await init_db()

    logger.info("🤖 EyellizSPY запущен")
    logger.info("📝 Отслеживание всех типов сообщений")
    logger.info("📁 Медиафайлы отправляются при удалении")
    logger.info(f"💾 Временная папка: {TEMP_DIR}")

    asyncio.create_task(periodic_cleanup())
    asyncio.create_task(cleanup_temp_files())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())