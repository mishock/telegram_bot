import asyncio
import sqlite3
import os
import json
import random
import csv
import io
import re
import urllib.request
from datetime import datetime
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv
from openai import OpenAI

# Загружаем переменные окружения
load_dotenv()

# ============================================
# НАСТРОЙКИ
# ============================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в файле .env")
    exit(1)

if not DEEPSEEK_API_KEY:
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: DEEPSEEK_API_KEY не найден, бот будет работать в режиме локальной базы знаний")

# Папка для логов
LOGS_DIR = "user_logs"
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Папка для экспортов
EXPORTS_DIR = "exports"
if not os.path.exists(EXPORTS_DIR):
    os.makedirs(EXPORTS_DIR)

# Файл с базой знаний ответов (резерв)
KNOWLEDGE_FILE = "knowledge_base.json"

# Файл со списком ID для рассылки
BROADCAST_IDS_FILE = "broadcast_ids.txt"

# Файл с system_prompt для DeepSeek
SYSTEM_PROMPT_FILE = "system_prompt.txt"

# Файлы инструкций и сервиса для отправки пользователю
SERVICE_DOC_FILES = [
    "knowledge/service/diligence_service_book_2026.pdf",
    "knowledge/service/yak_service_book.pdf",
    "knowledge/service/yak_washer_service_book.pdf",
]

INSTRUCTION_DOC_FILES = {
    "Як": "knowledge/instructions/yak_manual_2025.pdf",
    "Дилижанс": "knowledge/instructions/diligence_manual_2025.pdf",
    "Поливомоечная машина": "knowledge/instructions/washer_operation_manual.pdf",
}

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1c9__Xbrq8RAfEjphu-Sb4iS3WnHMLDYc4SIcVhVqNzU/export?format=csv&gid=0"
)
MAINTENANCE_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1II4KEQZHzkfzabq9wgCuIOyVaOhl-9nNgUYLQky328s/export?format=csv&gid=1469311667"
)

# Файл для постоянного экспорта пользователей
USERS_EXPORT_FILE = os.path.join(EXPORTS_DIR, "users_export.csv")

# Состояния для ConversationHandler
PHONE_REQUEST = 1

# Создаём файл broadcast_ids.txt если его нет
if not os.path.exists(BROADCAST_IDS_FILE):
    with open(BROADCAST_IDS_FILE, "w", encoding="utf-8") as f:
        f.write("")
    print(f"✅ Создан файл {BROADCAST_IDS_FILE}")

# Настройка DeepSeek клиента
if DEEPSEEK_API_KEY:
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
    AI_MODE = "deepseek"
    print("✅ DeepSeek AI подключен")
else:
    AI_MODE = "local"
    print("✅ Режим локальной базы знаний")

# ============================================
# ЗАГРУЗКА SYSTEM_PROMPT ИЗ ФАЙЛА
# ============================================

def load_system_prompt():
    """Загружает system_prompt из файла system_prompt.txt"""
    if os.path.exists(SYSTEM_PROMPT_FILE):
        with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        default_prompt = """Ты — официальный AI-консультант компании ЭЛЬТАВР, российского производителя коммерческого электротранспорта.

Твоя задача — не просто отвечать на вопросы, а помогать клиенту подобрать решение под конкретную задачу.

Правила ответов:
- Отвечай вежливо, полезно и по делу
- Будь краток и конкретен (2-3 предложения)
- Используй эмодзи где уместно
- Отвечай на том же языке, что и пользователь

Будь полезным помощником компании ЭЛЬТАВР!"""
        
        with open(SYSTEM_PROMPT_FILE, "w", encoding="utf-8") as f:
            f.write(default_prompt)
        print(f"✅ Создан файл {SYSTEM_PROMPT_FILE}")
        return default_prompt

SYSTEM_PROMPT = load_system_prompt()
print(f"📝 Загружен system_prompt из {SYSTEM_PROMPT_FILE}")

# ============================================
# АВТОМАТИЧЕСКОЕ ДОБАВЛЕНИЕ ID
# ============================================

def sync_ids_from_logs():
    """Синхронизирует ID из папки user_logs с файлом broadcast_ids.txt"""
    log_ids = set()
    if os.path.exists(LOGS_DIR):
        for filename in os.listdir(LOGS_DIR):
            if filename.endswith('.txt'):
                try:
                    user_id = int(filename.replace('.txt', ''))
                    log_ids.add(user_id)
                except ValueError:
                    pass
    
    current_ids = set(load_broadcast_ids())
    new_ids = log_ids - current_ids
    
    if new_ids:
        all_ids = list(current_ids | log_ids)
        save_broadcast_ids(all_ids)
        print(f"🆕 Добавлены новые ID: {len(new_ids)} шт.")
        return True, new_ids
    return False, set()

# ============================================
# РАБОТА СО СПИСКОМ ID
# ============================================

def load_broadcast_ids():
    """Загружает список ID из файла для рассылки"""
    if os.path.exists(BROADCAST_IDS_FILE):
        with open(BROADCAST_IDS_FILE, "r", encoding="utf-8") as f:
            ids = [line.strip() for line in f if line.strip()]
            return [int(id_str) for id_str in ids if id_str.isdigit()]
    return []

def save_broadcast_ids(ids_list):
    """Сохраняет список ID в файл"""
    with open(BROADCAST_IDS_FILE, "w", encoding="utf-8") as f:
        for user_id in ids_list:
            f.write(f"{user_id}\n")

def add_broadcast_id(user_id):
    """Добавляет ID в список для рассылки"""
    ids = load_broadcast_ids()
    if user_id not in ids:
        ids.append(user_id)
        save_broadcast_ids(ids)
        return True
    return False

def remove_broadcast_id(user_id):
    """Удаляет ID из списка для рассылки"""
    ids = load_broadcast_ids()
    if user_id in ids:
        ids.remove(user_id)
        save_broadcast_ids(ids)
        return True
    return False

def get_broadcast_stats():
    """Получает статистику по списку рассылки"""
    ids = load_broadcast_ids()
    return len(ids), ids

# ============================================
# ЭКСПОРТ ПОЛЬЗОВАТЕЛЕЙ В CSV
# ============================================

def export_users_to_csv():
    """Экспортирует всех пользователей в CSV файл на сервере"""
    cursor.execute("SELECT user_id, username, first_name, last_name, phone, email, registered_at FROM users")
    users = cursor.fetchall()
    
    if not users:
        return False, 0
    
    try:
        with open(USERS_EXPORT_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["ID", "Username", "Имя", "Фамилия", "Телефон", "Email", "Дата регистрации"])
            for user in users:
                writer.writerow([
                    user[0],
                    user[1] or "",
                    user[2] or "",
                    user[3] or "",
                    user[4] or "",
                    user[5] or "",
                    user[6] or ""
                ])
        
        print(f"✅ Экспорт сохранён на сервере: {USERS_EXPORT_FILE} ({len(users)} пользователей)")
        return True, len(users)
    except Exception as e:
        print(f"❌ Ошибка сохранения экспорта: {e}")
        return False, 0

# ============================================
# ЛОКАЛЬНАЯ БАЗА ЗНАНИЙ (РЕЗЕРВ)
# ============================================

def load_knowledge_base():
    """Загружает базу знаний из файла knowledge_base.json"""
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        default_kb = {
            "responses": [
                {
                    "keywords": ["компания", "о вас", "кто вы", "эльтавр"],
                    "response": "🏢 ЭЛЬТАВР - производитель коммерческого электротранспорта. Основана в 2014 году в Симферополе."
                },
                {
                    "keywords": ["мощность", "характеристики"],
                    "response": "⚡ Технические характеристики уточняйте на сайте eltavr.ru"
                },
                {
                    "keywords": ["цена", "стоимость"],
                    "response": "💰 Стоимость зависит от комплектации. Оставьте заявку на сайте eltavr.ru"
                }
            ],
            "default_response": "📝 Уточните вопрос на сайте eltavr.ru",
            "fallback_responses": ["🤔 Не совсем понял. Уточните вопрос."]
        }
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            json.dump(default_kb, f, ensure_ascii=False, indent=2)
        print("✅ Создан файл knowledge_base.json")
        return default_kb

def get_local_response(user_message):
    """Находит ответ в локальной базе знаний"""
    kb = load_knowledge_base()
    user_msg = user_message.lower()
    
    for rule in kb.get("responses", []):
        for keyword in rule.get("keywords", []):
            if keyword.lower() in user_msg:
                return rule.get("response")
    
    fallbacks = kb.get("fallback_responses", [])
    return random.choice(fallbacks) if fallbacks else kb.get("default_response")

# ============================================
# ПОЛУЧЕНИЕ КОНТЕКСТА ИЗ ИСТОРИИ ДИАЛОГА
# ============================================

def get_chat_context(user_id: int, last_n: int = 6) -> str:
    """Получает последние сообщения из лога для контекста"""
    log_file = os.path.join(LOGS_DIR, f"{user_id}.txt")
    
    if not os.path.exists(log_file):
        return ""
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        recent = lines[-last_n*2:] if len(lines) > last_n*2 else lines
        
        context = "📜 История диалога:\n"
        for line in recent:
            if "👤" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    context += f"👤 Пользователь: {parts[2].strip()}\n"
            elif "🤖" in line and "РАССЫЛКА" not in line:
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    context += f"🤖 Бот: {parts[2].strip()}\n"
        
        return context + "\n---\n"
    except Exception as e:
        print(f"Ошибка чтения истории: {e}")
        return ""

# ============================================
# AI ФУНКЦИЯ DEEPSEEK
# ============================================

async def get_ai_response(user_message: str, user_id: int, username: str = None) -> str:
    """Получает ответ от DeepSeek AI с учётом истории диалога"""
    
    if AI_MODE != "deepseek":
        return get_local_response(user_message)
    
    try:
        current_system_prompt = load_system_prompt()
        
        chat_history = get_chat_context(user_id, last_n=6)
        
        if chat_history:
            full_prompt = f"{chat_history}\n👉 Текущий вопрос пользователя: {user_message}"
            print(f"📜 История диалога для {user_id} передана в AI")
        else:
            full_prompt = user_message
        
        # Модели DeepSeek
        models_to_try = [
            "deepseek-chat",
            "deepseek-coder",
        ]
        
        last_error = None
        
        for model_name in models_to_try:
            try:
                print(f"🔄 Пробуем модель DeepSeek: {model_name}")
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": current_system_prompt},
                        {"role": "user", "content": full_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=500
                )
                print(f"✅ Успешно с моделью: {model_name}")
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                print(f"❌ Модель {model_name} не работает: {e}")
                continue
        
        print(f"❌ Все модели DeepSeek недоступны: {last_error}")
        return get_local_response(user_message)
        
    except Exception as e:
        print(f"❌ Ошибка DeepSeek: {e}")
        return get_local_response(user_message)

# ============================================
# БАЗА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================

def init_db():
    """Инициализирует базу данных"""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            email TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'last_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
    if 'phone' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    if 'email' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
    
    conn.commit()
    return conn, cursor

db, cursor = init_db()

# При запуске создаём начальный экспорт
export_users_to_csv()

# ============================================
# ЛОГИРОВАНИЕ ПЕРЕПИСКИ
# ============================================

def log_message(user_id, direction, text, username=None):
    """Сохраняет сообщение в файл пользователя"""
    filename = os.path.join(LOGS_DIR, f"{user_id}.txt")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if direction == "USER":
        log_entry = f"[{timestamp}] 👤 {username or 'user'}: {text}\n"
    else:
        log_entry = f"[{timestamp}] 🤖 БОТ: {text}\n"
    
    with open(filename, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    if direction == "USER":
        if add_broadcast_id(user_id):
            print(f"🆕 Добавлен ID {user_id} в список рассылки")

def is_admin(user_id):
    return user_id == ADMIN_ID

# ============================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ТЕЛЕФОНОМ
# ============================================

async def request_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает номер телефона у пользователя"""
    user_id = update.effective_user.id
    
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result and result[0]:
        await update.message.reply_text("✅ Ваш номер телефона уже сохранён в системе.")
        return ConversationHandler.END
    
    button = KeyboardButton("📱 Отправить номер телефона", request_contact=True)
    reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "📞 Для более качественной поддержки, пожалуйста, поделитесь своим номером телефона.\n\n"
        "Это поможет нашему менеджеру связаться с вами при необходимости.\n\n"
        "Нажмите на кнопку ниже:",
        reply_markup=reply_markup
    )
    return PHONE_REQUEST

async def save_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет номер телефона пользователя"""
    contact = update.message.contact
    user_id = update.effective_user.id
    
    if contact and contact.user_id == user_id:
        phone = contact.phone_number
        
        cursor.execute(
            "UPDATE users SET phone = ? WHERE user_id = ?",
            (phone, user_id)
        )
        db.commit()
        
        export_users_to_csv()
        
        reply_markup = ReplyKeyboardRemove()
        
        await update.message.reply_text(
            "✅ Спасибо! Ваш номер телефона сохранён.\n\n"
            "Теперь я смогу лучше помочь вам с подбором транспорта.\n\n"
            "Задавайте любые вопросы!",
            reply_markup=reply_markup
        )
    
    return ConversationHandler.END

async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропускает запрос телефона"""
    await update.message.reply_text(
        "Хорошо, продолжим без номера телефона.\n\n"
        "Вы всегда можете поделиться им позже командой /phone"
    )
    return ConversationHandler.END

async def show_my_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пользователю его сохранённый номер телефона"""
    user_id = update.effective_user.id
    cursor.execute("SELECT phone FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result and result[0]:
        await update.message.reply_text(f"📞 Ваш номер телефона: `{result[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❌ У вас ещё не сохранён номер телефона.\n\n"
            "Отправьте /phone чтобы добавить его."
        )

# ============================================
# АДМИН КОМАНДЫ
# ============================================

async def set_user_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ команда: /setphone 123456789 +71234567890"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ Пример: /setphone 123456789 +71234567890")
        return
    
    try:
        user_id = int(args[0])
        phone = args[1]
        
        cursor.execute(
            "UPDATE users SET phone = ? WHERE user_id = ?",
            (phone, user_id)
        )
        db.commit()
        
        export_users_to_csv()
        
        if cursor.rowcount > 0:
            await update.message.reply_text(f"✅ Телефон {phone} сохранён для пользователя {user_id}")
        else:
            await update.message.reply_text(f"⚠️ Пользователь {user_id} не найден")
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

async def set_user_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ команда: /setemail 123456789 user@example.com"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ Пример: /setemail 123456789 user@example.com")
        return
    
    try:
        user_id = int(args[0])
        email = args[1]
        
        cursor.execute(
            "UPDATE users SET email = ? WHERE user_id = ?",
            (email, user_id)
        )
        db.commit()
        
        export_users_to_csv()
        
        if cursor.rowcount > 0:
            await update.message.reply_text(f"✅ Email {email} сохранён для пользователя {user_id}")
        else:
            await update.message.reply_text(f"⚠️ Пользователь {user_id} не найден")
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

async def export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует пользователей в CSV"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    success, count = export_users_to_csv()
    
    if not success:
        await update.message.reply_text("❌ Нет пользователей для экспорта")
        return
    
    try:
        with open(USERS_EXPORT_FILE, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                caption=f"📊 Экспорт пользователей\n\n👥 Всего: {count}\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
        
        print(f"✅ Экспорт отправлен в Telegram")
        
    except Exception as e:
        print(f"❌ Ошибка отправки экспорта: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def get_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ команда: /userinfo 123456789"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Пример: /userinfo 123456789")
        return
    
    try:
        user_id = int(context.args[0])
        cursor.execute("SELECT user_id, username, first_name, last_name, phone, email, registered_at FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if user:
            info = f"📋 **Информация о пользователе**\n\n"
            info += f"🆔 ID: `{user[0]}`\n"
            info += f"👤 Username: @{user[1] if user[1] else 'Нет'}\n"
            info += f"📛 Имя: {user[2] if user[2] else 'Не указано'}\n"
            info += f"📛 Фамилия: {user[3] if user[3] else 'Не указана'}\n"
            info += f"📞 Телефон: {user[4] if user[4] else 'Не указан'}\n"
            info += f"📧 Email: {user[5] if user[5] else 'Не указан'}\n"
            info += f"📅 Зарегистрирован: {user[6] if user[6] else 'Неизвестно'}"
            
            await update.message.reply_text(info, parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Пользователь {user_id} не найден")
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

# ============================================
# КОМАНДЫ БОТА
# ============================================

SERVICE_BUTTON_TEXT = "Сервис"
INSTRUCTIONS_BUTTON_TEXT = "Инструкции"
YAK_INSTRUCTION_TEXT = "Як"
DILIGENCE_INSTRUCTION_TEXT = "Дилижанс"
WASHER_INSTRUCTION_TEXT = "Поливомоечная машина"
SERVICE_BOOKS_BUTTON_TEXT = "Сервисные книжки"
SERVICE_VIN_BUTTON_TEXT = "Поиск по VIN"
SERVICE_MAINTENANCE_BUTTON_TEXT = "Плановое ТО"
BACK_TO_MAIN_MENU_TEXT = "Главное меню"
AWAITING_INSTRUCTION_KEY = "awaiting_instruction_vehicle"
AWAITING_FRAME_LOOKUP_KEY = "awaiting_frame_lookup"
AWAITING_MAINTENANCE_LOOKUP_KEY = "awaiting_maintenance_lookup"
SERVICE_SUBMENU_KEY = "service_submenu_active"

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[SERVICE_BUTTON_TEXT, INSTRUCTIONS_BUTTON_TEXT]],
        resize_keyboard=True
    )

def get_service_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [SERVICE_BOOKS_BUTTON_TEXT, SERVICE_VIN_BUTTON_TEXT],
            [SERVICE_MAINTENANCE_BUTTON_TEXT],
            [BACK_TO_MAIN_MENU_TEXT],
        ],
        resize_keyboard=True,
    )

def get_instruction_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [YAK_INSTRUCTION_TEXT, DILIGENCE_INSTRUCTION_TEXT],
            [WASHER_INSTRUCTION_TEXT],
            [BACK_TO_MAIN_MENU_TEXT],
        ],
        resize_keyboard=True,
    )

async def send_doc_if_exists(update: Update, file_path: str) -> bool:
    """Отправляет документ, если файл существует."""
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "rb") as doc_file:
            await update.message.reply_document(document=doc_file)
        return True
    except Exception as e:
        print(f"⚠️ Ошибка отправки файла {file_path}: {e}")
        return False

def normalize_frame_number(value: str) -> str:
    """Нормализует номер рамы для строгого сравнения."""
    normalized = (value or "").upper().strip()
    normalized = normalized.replace("*", "").replace("'", "").replace('"', "")
    normalized = "".join(normalized.split())
    # Приводим похожие кириллические символы к латинице.
    cyr_to_lat = str.maketrans({
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H",
        "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
        "Х": "X", "У": "Y",
    })
    return normalized.translate(cyr_to_lat)

def normalize_header(value: str) -> str:
    """Нормализует заголовок колонки для поиска по имени."""
    return " ".join((value or "").strip().lower().replace("ё", "е").split())


def parse_date_safe(value: str):
    """Пробует распарсить дату из строки в популярных форматах."""
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def get_frame_data_from_sheet(frame_number: str):
    """
    Возвращает данные по номеру рамы из публичного CSV Google Sheets.
    Ищет колонки по их названиям в строке заголовков.
    """
    try:
        with urllib.request.urlopen(SHEET_CSV_URL, timeout=15) as response:
            content = response.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        return None, f"Ошибка доступа к таблице: {e}"

    rows = list(csv.reader(io.StringIO(content)))
    if not rows:
        return None, "Таблица пуста."

    header_aliases = {
        "frame": {
            "№ рамы", "номер рамы", "vin", "vin номер", "vin-код", "vin код", "машина"
        },
        "config": {"комплектация"},
        "customer": {"заказчик", "клиент"},
        "ship_date": {"дата отгрузки заказчику", "дата отгрузки", "отгрузка"},
        "service_date": {"дата планового то", "плановое то", "дата то"},
    }

    normalized_aliases = {
        key: {normalize_header(alias) for alias in aliases}
        for key, aliases in header_aliases.items()
    }

    header_row_index = None
    header_map = {}
    for idx, row in enumerate(rows[:30]):
        current_map = {}
        for col_idx, cell in enumerate(row):
            cell_norm = normalize_header(cell)
            if not cell_norm:
                continue
            for key, aliases in normalized_aliases.items():
                if key not in current_map and cell_norm in aliases:
                    current_map[key] = col_idx
        if "frame" in current_map:
            header_row_index = idx
            header_map = current_map
            break

    if header_row_index is None:
        return None, "Не удалось найти заголовки в таблице."

    target = normalize_frame_number(frame_number)
    for row in rows[header_row_index + 1:]:
        frame_idx = header_map.get("frame")
        if frame_idx is None or len(row) <= frame_idx:
            continue
        row_frame = normalize_frame_number(row[frame_idx])
        if row_frame == target:
            # По требованию: поле "Машина" выдаём строго из колонки B.
            machine_from_col_b = row[1].strip() if len(row) > 1 else ""
            data = {
                "machine": machine_from_col_b,
                "config": row[header_map["config"]].strip()
                if "config" in header_map and len(row) > header_map["config"] else "",
                "customer": row[header_map["customer"]].strip()
                if "customer" in header_map and len(row) > header_map["customer"] else "",
                "ship_date": row[header_map["ship_date"]].strip()
                if "ship_date" in header_map and len(row) > header_map["ship_date"] else "",
                "service_date": row[header_map["service_date"]].strip()
                if "service_date" in header_map and len(row) > header_map["service_date"] else "",
            }
            return data, None

    return None, None


def get_maintenance_data_from_sheet(frame_number: str):
    """
    Ищет VIN в колонке "Шасси" и возвращает:
    - дату продажи
    - все плановые ТО из колонок 1..5
    """
    try:
        with urllib.request.urlopen(MAINTENANCE_SHEET_CSV_URL, timeout=15) as response:
            content = response.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        return None, f"Ошибка доступа к таблице ТО: {e}"

    rows = list(csv.reader(io.StringIO(content)))
    if not rows:
        return None, "Таблица ТО пуста."

    chassis_aliases = {"шасси"}
    sale_aliases = {"дата продажи"}
    fallback_chassis_idx = 4  # Колонка E
    fallback_contacts_idx = 2  # Колонка C
    fallback_machine_name_idx = 3  # Колонка D

    header_row_index = None
    chassis_idx = None
    sale_idx = None
    maintenance_cols = {}

    for idx, row in enumerate(rows[:30]):
        normalized = [normalize_header(cell) for cell in row]
        for col_idx, col_name in enumerate(normalized):
            if chassis_idx is None and col_name in chassis_aliases:
                chassis_idx = col_idx
            if sale_idx is None and col_name in sale_aliases:
                sale_idx = col_idx
            match = re.search(r"(\d+)\s*плановое то", col_name)
            if match:
                to_number = int(match.group(1))
                if 1 <= to_number <= 5:
                    maintenance_cols[to_number] = col_idx
        if chassis_idx is not None:
            header_row_index = idx
            break
        # reset for next potential header row
        chassis_idx = None
        sale_idx = None
        maintenance_cols = {}

    # Если заголовок "Шасси" не найден, используем фиксированную колонку E.
    if header_row_index is None:
        header_row_index = 0
    if chassis_idx is None:
        chassis_idx = fallback_chassis_idx

    target = normalize_frame_number(frame_number)
    for row in rows[header_row_index + 1:]:
        if len(row) <= chassis_idx:
            continue
        row_frame = normalize_frame_number(row[chassis_idx])
        if row_frame != target:
            continue

        sale_date = row[sale_idx].strip() if sale_idx is not None and len(row) > sale_idx else ""
        contacts = row[fallback_contacts_idx].strip() if len(row) > fallback_contacts_idx else ""
        machine_name = row[fallback_machine_name_idx].strip() if len(row) > fallback_machine_name_idx else ""

        maintenance_values = {}
        for to_number in range(1, 6):
            col_idx = maintenance_cols.get(to_number)
            value = ""
            if col_idx is not None and len(row) > col_idx:
                value = row[col_idx].strip()
            maintenance_values[f"to_{to_number}"] = value

        return {
            "sale_date": sale_date,
            "contacts": contacts,
            "machine_name": machine_name,
            "maintenance_values": maintenance_values,
        }, None

    return None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
        (user_id, username, first_name, last_name)
    )
    db.commit()
    
    export_users_to_csv()
    add_broadcast_id(user_id)
    log_message(user_id, "USER", "/start", username)
    
    welcome = f"""🏢 Здравствуйте, {first_name}!

Я бот поддержки компании ЭЛЬТАВР с AI от DeepSeek.

🚗 Мы производим коммерческий электротранспорт:
• Электробусы «Дилижанс»
• Электрогрузовики «Як»
• Спецтехника

💬 Напишите ваш вопрос, и я помогу!

Для связи с менеджером: /phone"""
    
    log_message(user_id, "BOT", welcome, username)
    await update.message.reply_text(welcome, reply_markup=get_main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда help"""
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Команда /help доступна только администратору.")
        return

    help_text = """🔐 **АДМИН ПАНЕЛЬ**

📚 **Команды рассылки:**
/broadcast текст - рассылка всем
/broadcastfile - рассылка из файла message.txt
/broadcastids 123,456 | текст - рассылка по ID
/broadcastlist - список ID
/addid ID - добавить ID
/removeid ID - удалить ID
/clearids - очистить список

📊 **Статистика и логи:**
/stats - статистика
/getlog ID - лог пользователя
/listlogs - список логов
/synclogs - синхронизация ID

👥 **Управление:**
/userinfo ID - информация о пользователе
/setphone ID телефон - установить телефон
/setemail ID email - установить email
/exportusers - экспорт в CSV

📞 **Телефон:**
/phone - запросить номер
/myphone - показать свой номер

🤖 **AI:** DeepSeek"""

    await update.message.reply_text(help_text, parse_mode="Markdown")

# === КОМАНДЫ РАССЫЛКИ ===

async def broadcast_to_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Пример: /broadcast Всем привет!")
        return
    
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    if not users:
        await update.message.reply_text("Нет пользователей")
        return
    
    sent = 0
    await update.message.reply_text(f"📢 Рассылка для {len(users)} пользователей...")
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=f"📢 {text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await update.message.reply_text(f"✅ Отправлено: {sent}")

async def broadcast_from_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    message_file = "message.txt"
    
    if not os.path.exists(message_file):
        await update.message.reply_text(f"❌ Файл {message_file} не найден!")
        return
    
    ids = load_broadcast_ids()
    if not ids:
        await update.message.reply_text(f"❌ Список ID пуст!")
        return
    
    with open(message_file, "r", encoding="utf-8") as f:
        message_text = f.read().strip()
    
    await update.message.reply_text(f"📢 Рассылка для {len(ids)} пользователей...")
    
    sent = 0
    for user_id in ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await update.message.reply_text(f"✅ Отправлено: {sent}")

async def broadcast_by_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    args = " ".join(context.args)
    parts = args.split("|")
    
    if len(parts) < 2:
        await update.message.reply_text("❌ Формат: /broadcastids 123,456 | Текст")
        return
    
    ids_str = parts[0].strip()
    message_text = parts[1].strip()
    
    try:
        ids_list = [int(id_str.strip()) for id_str in ids_str.split(",")]
    except ValueError:
        await update.message.reply_text("❌ ID должны быть числами")
        return
    
    sent = 0
    for user_id in ids_list:
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await update.message.reply_text(f"✅ Отправлено: {sent}")

async def show_broadcast_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    count, ids = get_broadcast_stats()
    
    if not ids:
        await update.message.reply_text("📭 Список ID пуст.")
        return
    
    text = f"📋 СПИСОК ID (всего: {count})\n\n"
    for i, user_id in enumerate(ids[:30], 1):
        text += f"{i}. {user_id}\n"
    
    if len(ids) > 30:
        text += f"\n... и еще {len(ids) - 30}"
    
    await update.message.reply_text(text)

async def add_broadcast_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Пример: /addid 123456789")
        return
    
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return
    
    if add_broadcast_id(user_id):
        await update.message.reply_text(f"✅ ID {user_id} добавлен")
    else:
        await update.message.reply_text(f"⚠️ ID {user_id} уже есть")

async def remove_broadcast_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Пример: /removeid 123456789")
        return
    
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")
        return
    
    if remove_broadcast_id(user_id):
        await update.message.reply_text(f"✅ ID {user_id} удален")
    else:
        await update.message.reply_text(f"⚠️ ID {user_id} не найден")

async def clear_broadcast_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    save_broadcast_ids([])
    await update.message.reply_text("✅ Список очищен")

async def sync_logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    added, new_ids = sync_ids_from_logs()
    
    if added:
        await update.message.reply_text(f"✅ Добавлено ID: {len(new_ids)}")
    else:
        await update.message.reply_text("✅ Новых ID не найдено")

# === СТАТИСТИКА ===

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL AND phone != ''")
    users_with_phone = cursor.fetchone()[0]
    
    logs_count = len([f for f in os.listdir(LOGS_DIR) if f.endswith('.txt')])
    broadcast_count, _ = get_broadcast_stats()
    
    await update.message.reply_text(
        f"📊 СТАТИСТИКА\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"📞 С телефоном: {users_with_phone}\n"
        f"💬 Диалогов: {logs_count}\n"
        f"📋 ID в рассылке: {broadcast_count}\n"
        f"🤖 AI: DeepSeek"
    )

async def getlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Пример: /getlog 123456789")
        return
    
    try:
        user_id = int(context.args[0])
        log_file = os.path.join(LOGS_DIR, f"{user_id}.txt")
        
        if not os.path.exists(log_file):
            await update.message.reply_text(f"❌ Нет логов для {user_id}")
            return
        
        with open(log_file, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"user_{user_id}_log.txt",
                caption=f"📋 Лог пользователя {user_id}"
            )
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")

async def listlogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступно только администратору.")
        return
    
    logs = [f.replace('.txt', '') for f in os.listdir(LOGS_DIR) if f.endswith('.txt')]
    
    if not logs:
        await update.message.reply_text("📭 Нет логов")
        return
    
    text = f"📁 ПОЛЬЗОВАТЕЛИ (всего: {len(logs)})\n\n"
    for user_id in logs[:30]:
        cursor.execute("SELECT username, first_name FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if user and user[0]:
            text += f"• `{user_id}` - @{user[0]}\n"
        elif user and user[1]:
            text += f"• `{user_id}` - {user[1]}\n"
        else:
            text += f"• `{user_id}`\n"
    
    if len(logs) > 30:
        text += f"\n... и еще {len(logs) - 30}"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# === ОБРАБОТЧИК СООБЩЕНИЙ ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    text = update.message.text
    
    if text.startswith('/'):
        return

    if text == BACK_TO_MAIN_MENU_TEXT:
        context.user_data.pop(AWAITING_FRAME_LOOKUP_KEY, None)
        context.user_data.pop(AWAITING_MAINTENANCE_LOOKUP_KEY, None)
        context.user_data.pop(AWAITING_INSTRUCTION_KEY, None)
        context.user_data.pop(SERVICE_SUBMENU_KEY, None)
        response = "Главное меню."
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(response, reply_markup=get_main_menu_keyboard())
        return

    if text == SERVICE_BUTTON_TEXT:
        context.user_data.pop(AWAITING_INSTRUCTION_KEY, None)
        context.user_data[AWAITING_FRAME_LOOKUP_KEY] = False
        context.user_data[AWAITING_MAINTENANCE_LOOKUP_KEY] = False
        context.user_data[SERVICE_SUBMENU_KEY] = True
        response = (
            "Раздел сервиса.\n"
            "Сервисные книжки — три PDF для скачивания.\n"
            "Поиск по VIN — данные по отгрузке и комплектации.\n"
            "Плановое ТО — дата продажи и следующее ТО."
        )
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_service_keyboard(),
        )
        return

    if text == SERVICE_BOOKS_BUTTON_TEXT:
        context.user_data.pop(SERVICE_SUBMENU_KEY, None)
        context.user_data.pop(AWAITING_FRAME_LOOKUP_KEY, None)
        context.user_data.pop(AWAITING_MAINTENANCE_LOOKUP_KEY, None)
        log_message(user_id, "USER", text, username)
        intro = "Отправляю сервисные книжки файлами."
        log_message(user_id, "BOT", intro, username)
        await update.message.reply_text(intro, reply_markup=get_main_menu_keyboard())
        for path in SERVICE_DOC_FILES:
            await send_doc_if_exists(update, path)
        return

    if text == SERVICE_VIN_BUTTON_TEXT:
        context.user_data[SERVICE_SUBMENU_KEY] = True
        context.user_data[AWAITING_FRAME_LOOKUP_KEY] = True
        context.user_data[AWAITING_MAINTENANCE_LOOKUP_KEY] = False
        response = "Введите номер рамы — покажу машину, комплектацию, дату отгрузки и дату планового ТО."
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_service_keyboard(),
        )
        return

    if text == SERVICE_MAINTENANCE_BUTTON_TEXT:
        context.user_data[SERVICE_SUBMENU_KEY] = True
        context.user_data[AWAITING_FRAME_LOOKUP_KEY] = False
        context.user_data[AWAITING_MAINTENANCE_LOOKUP_KEY] = True
        response = "Введите VIN (Шасси) — покажу дату продажи и все плановые ТО (1-5)."
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_service_keyboard(),
        )
        return

    if context.user_data.get(SERVICE_SUBMENU_KEY) and not context.user_data.get(
        AWAITING_FRAME_LOOKUP_KEY
    ) and not context.user_data.get(AWAITING_MAINTENANCE_LOOKUP_KEY):
        response = "Выберите: «Сервисные книжки», «Поиск по VIN», «Плановое ТО» или «Главное меню»."
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_service_keyboard(),
        )
        return

    if context.user_data.get(AWAITING_FRAME_LOOKUP_KEY):
        frame_number = text.strip()
        frame_data, error = get_frame_data_from_sheet(frame_number)

        if error:
            response = f"Не удалось получить данные. {error}"
        elif frame_data is None:
            response = f"Номер рамы {frame_number} не найден."
        else:
            response = (
                f"Номер рамы: {frame_number}\n"
                f"Машина: {frame_data.get('machine') or 'не указана'}\n"
                f"Комплектация: {frame_data.get('config') or 'не указана'}\n"
                f"Дата отгрузки: {frame_data.get('ship_date') or 'не указана'}\n"
                f"Дата планового ТО: {frame_data.get('service_date') or 'не указана'}"
            )

        context.user_data[AWAITING_FRAME_LOOKUP_KEY] = False
        context.user_data.pop(SERVICE_SUBMENU_KEY, None)
        log_message(user_id, "USER", frame_number, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(response, reply_markup=get_main_menu_keyboard())
        return

    if context.user_data.get(AWAITING_MAINTENANCE_LOOKUP_KEY):
        frame_number = text.strip()
        maintenance_data, error = get_maintenance_data_from_sheet(frame_number)

        if error:
            response = f"Не удалось получить данные. {error}"
        elif maintenance_data is None:
            response = f"VIN/Шасси {frame_number} не найден."
        else:
            maintenance_values = maintenance_data.get("maintenance_values", {})
            response = (
                f"VIN/Шасси: {frame_number}\n"
                f"Машина: {maintenance_data.get('machine_name') or 'не указана'}\n"
                f"Контакты: {maintenance_data.get('contacts') or 'не указаны'}\n"
                f"Дата продажи: {maintenance_data.get('sale_date') or 'не указана'}\n"
                f"1 Плановое ТО: {maintenance_values.get('to_1') or 'не указано'}\n"
                f"2 Плановое ТО: {maintenance_values.get('to_2') or 'не указано'}\n"
                f"3 Плановое ТО: {maintenance_values.get('to_3') or 'не указано'}\n"
                f"4 Плановое ТО: {maintenance_values.get('to_4') or 'не указано'}\n"
                f"5 Плановое ТО: {maintenance_values.get('to_5') or 'не указано'}"
            )

        context.user_data[AWAITING_MAINTENANCE_LOOKUP_KEY] = False
        context.user_data.pop(SERVICE_SUBMENU_KEY, None)
        log_message(user_id, "USER", frame_number, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(response, reply_markup=get_main_menu_keyboard())
        return

    if text == INSTRUCTIONS_BUTTON_TEXT:
        context.user_data.pop(SERVICE_SUBMENU_KEY, None)
        context.user_data.pop(AWAITING_FRAME_LOOKUP_KEY, None)
        context.user_data.pop(AWAITING_MAINTENANCE_LOOKUP_KEY, None)
        context.user_data[AWAITING_INSTRUCTION_KEY] = True
        response = (
            "Выберите технику, по которой нужна инструкция:\n"
            f"• {YAK_INSTRUCTION_TEXT}\n"
            f"• {DILIGENCE_INSTRUCTION_TEXT}\n"
            f"• {WASHER_INSTRUCTION_TEXT}"
        )
        log_message(user_id, "USER", text, username)
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_instruction_keyboard()
        )
        return

    if context.user_data.get(AWAITING_INSTRUCTION_KEY):
        valid_instruction_targets = {
            YAK_INSTRUCTION_TEXT,
            DILIGENCE_INSTRUCTION_TEXT,
            WASHER_INSTRUCTION_TEXT
        }
        if text not in valid_instruction_targets:
            response = (
                "Пожалуйста, выберите технику кнопкой:\n"
                f"• {YAK_INSTRUCTION_TEXT}\n"
                f"• {DILIGENCE_INSTRUCTION_TEXT}\n"
                f"• {WASHER_INSTRUCTION_TEXT}"
            )
            log_message(user_id, "USER", text, username)
            log_message(user_id, "BOT", response, username)
            await update.message.reply_text(
                response,
                reply_markup=get_instruction_keyboard()
            )
            return

        context.user_data[AWAITING_INSTRUCTION_KEY] = False
        log_message(user_id, "USER", text, username)
        await update.message.chat.send_action(action="typing")
        response = (
            f"Вы запросили инструкцию на {text}. "
            "Подробную инструкцию отправляю файлом для ознакомления и скачивания."
        )
        log_message(user_id, "BOT", response, username)
        await update.message.reply_text(
            response,
            reply_markup=get_main_menu_keyboard()
        )
        selected_doc = INSTRUCTION_DOC_FILES.get(text)
        if selected_doc:
            await send_doc_if_exists(update, selected_doc)
        return
    
    # Защита от грубостей
    rude_words = ["гандон", "дурак", "идиот", "козел", "сволочь", "тварь", "сука"]
    if any(word in text.lower() for word in rude_words):
        response = "🙏 Пожалуйста, общайтесь вежливо. Я здесь, чтобы помочь вам."
        await update.message.reply_text(response)
        return
    
    log_message(user_id, "USER", text, username)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {user_id}: {text[:50]}")
    
    await update.message.chat.send_action(action="typing")
    await asyncio.sleep(0.3)
    
    response = await get_ai_response(text, user_id, username)
    
    log_message(user_id, "BOT", response, username)
    await update.message.reply_text(response, reply_markup=get_main_menu_keyboard())

# ============================================
# ЗАПУСК БОТА
# ============================================

def main():
    print("=" * 50)
    print("🏢 БОТ ПОДДЕРЖКИ ЭЛЬТАВР (DeepSeek AI)")
    print("=" * 50)
    print(f"Администратор: {ADMIN_ID}")
    print(f"Логи: {LOGS_DIR}/")
    print(f"Режим: {'DeepSeek AI' if AI_MODE == 'deepseek' else 'Локальная база'}")
    print(f"Файл ID: {BROADCAST_IDS_FILE}")
    print("=" * 50)
    
    sync_ids_from_logs()
    print("✅ Бот готов!")
    
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для телефона
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("phone", request_phone)],
        states={
            PHONE_REQUEST: [
                MessageHandler(filters.CONTACT, save_phone),
                CommandHandler("skip", skip_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, skip_phone)
            ]
        },
        fallbacks=[CommandHandler("skip", skip_phone)]
    )
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myphone", show_my_phone))
    application.add_handler(conv_handler)
    
    # Админ команды
    application.add_handler(CommandHandler("broadcast", broadcast_to_all))
    application.add_handler(CommandHandler("broadcastfile", broadcast_from_file))
    application.add_handler(CommandHandler("broadcastids", broadcast_by_ids))
    application.add_handler(CommandHandler("broadcastlist", show_broadcast_list))
    application.add_handler(CommandHandler("addid", add_broadcast_id_command))
    application.add_handler(CommandHandler("removeid", remove_broadcast_id_command))
    application.add_handler(CommandHandler("clearids", clear_broadcast_ids))
    application.add_handler(CommandHandler("synclogs", sync_logs_command))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("getlog", getlog))
    application.add_handler(CommandHandler("listlogs", listlogs))
    application.add_handler(CommandHandler("userinfo", get_user_info))
    application.add_handler(CommandHandler("setphone", set_user_phone))
    application.add_handler(CommandHandler("setemail", set_user_email))
    application.add_handler(CommandHandler("exportusers", export_users))
    
    # Обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")