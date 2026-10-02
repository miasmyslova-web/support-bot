import os
import asyncio
import random
import json
import tempfile
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from openai import OpenAI
from aiohttp import web

print("=== БОТ ЗАПУСКАЕТСЯ ===")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ===== ХРАНИЛИЩА =====
HISTORY = defaultdict(list)
MOOD_LOG = defaultdict(list)
REMINDERS = []
USER_PROFILES = {}   # {chat_id: {"name": ..., "age_group": ..., "style": ..., "topic": ...}}
ONBOARDED = set()

MAX_HISTORY = 20

FREE_MODELS = [
    "nvidia/nemotron-3-super:free",
    "qwen/qwen-3-8-27b:free",
    "google/gemma-4-31b-it:free",
    "dots-studio/dots-3-note-preview:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

VOICE_MODEL = "google/gemini-2.0-flash-exp:free"

# ===== ПРОМПТЫ ПО ВОЗРАСТУ =====
def get_system_prompt(age_group: str = "unknown", style: str = "soft") -> str:
    base = """Ты — эмпатичный и поддерживающий ассистент-психолог. 
Не ставь диагнозы и не давай медицинских советов. 
Отвечай тепло, по-человечески, без шаблонных фраз. 
Помни контекст разговора."""

    age_additions = {
        "teen": """
ВАЖНО: Пользователь — подросток (13-17 лет). 
Говори простым, дружелюбным языком, как старший друг. 
Не используй сложные психологические термины. 
Будь особенно бережен — у подростков сильные эмоции. 
Избегай нравоучений и фраз «в твоём возрасте». 
Не обесценивай проблемы («это ерунда», «перерастёшь»).""",

        "young": """
Пользователь — молодой человек (18-25 лет). 
Говори на равных, современно, но с заботой. 
Можно использовать лёгкие метафоры. 
Будь прямым, но тёплым.""",

        "adult": """
Пользователь — взрослый человек (26-45 лет). 
Говори уважительно, по-взрослому. 
Можно обсуждать сложные темы — работу, семью, смысл. 
Не упрощай.""",

        "older": """
Пользователь — человек старшего возраста (46+). 
Говори уважительно, тепло, без сюсюканья. 
Признавай жизненный опыт. 
Будь особенно терпелив.""",

        "unknown": "",
    }

    style_additions = {
        "soft": "\nОбщайся мягко и бережно. Много поддержки, мало прямых вопросов.",
        "direct": "\nОбщайся прямо и по делу. Задавай конкретные вопросы.",
        "humor": "\nМожно легко и с юмором, но не переигрывай. Юмор — не вместо эмпатии.",
    }

    return base + age_additions.get(age_group, "") + style_additions.get(style, "")

# ===== КРИЗИС =====
CRISIS_WORDS = [
    "умираю", "умереть", "умру", "смерть", "мёртв", "мертв",
    "суицид", "самоубий", "покончить с собой", "покончить жизнь",
    "убить себя", "убью себя", "не хочу жить", "не хочу больше жить",
    "хочу умереть", "хочу сдохнуть", "нет смысла жить", "жизнь не имеет смысла",
    "резать себя", "порезы", "порезал", "порезала", "вскрыть вены",
    "вскрыл вены", "вскрыла вены", "режу вены",
    "повеситься", "повешусь", "спрыгнуть с крыши", "спрыгнуть с моста",
    "наглотаться таблеток", "выпить таблетки", "передозировка",
    "прощай", "прощайте", "я больше не могу", "нет выхода",
    "всё кончено", "все кончено", "это конец", "хочу исчезнуть",
]

CRISIS_REPLY = """Я слышу тебя. То, что ты сейчас чувствуешь — это очень тяжело, и я хочу, чтобы ты знал: ты не один.

Пожалуйста, прямо сейчас позвони туда, где тебе помогут живые люди:

📞 8-800-2000-122 — бесплатный телефон доверия (круглосуточно, анонимно, по всей России)
📞 8-495-989-50-50 — круглосуточная психологическая помощь
📞 8-800-333-44-34 — Всероссийская линия помощи
📞 112 — единый номер экстренных служб

Ты важен. Пожалуйста, не оставайся с этим один."""

def is_crisis(text: str) -> bool:
    low = text.lower()
    return any(word in low for word in CRISIS_WORDS)

def add_to_history(chat_id: int, role: str, content: str):
    HISTORY[chat_id].append({"role": role, "content": content})
    if len(HISTORY[chat_id]) > MAX_HISTORY:
        HISTORY[chat_id] = HISTORY[chat_id][-MAX_HISTORY:]

# ===== ФРАЗЫ =====
FAREWELLS = [
    "Спасибо, что поговорил со мной. Береги себя 💙",
    "Я рядом, если снова понадоблюсь. Хорошего дня!",
    "Спасибо за доверие. Заглядывай, когда захочется поговорить.",
    "Береги себя. Ты важен 🌿",
]

ERROR_REPLIES = [
    "Ой, я немного задумался. Напиши ещё раз, пожалуйста.",
    "Прости, что-то я завис. Повтори, пожалуйста.",
    "Извини, я отвлёкся. Что ты хотел сказать?",
]

# ===== ОНБОРДИНГ =====
def get_age_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧑 13–17 лет", callback_data="age_teen")],
        [InlineKeyboardButton(text="🧑‍🎓 18–25 лет", callback_data="age_young")],
        [InlineKeyboardButton(text="🧑‍💼 26–45 лет", callback_data="age_adult")],
        [InlineKeyboardButton(text="🧓 46+ лет", callback_data="age_older")],
        [InlineKeyboardButton(text="🤐 Не хочу говорить", callback_data="age_skip")],
    ])

def get_style_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Мягко и бережно", callback_data="style_soft")],
        [InlineKeyboardButton(text="💬 Прямо и по делу", callback_data="style_direct")],
        [InlineKeyboardButton(text="✨ С юмором и легко", callback_data="style_humor")],
    ])

def get_topics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😰 Тревога", callback_data="topic_тревога")],
        [InlineKeyboardButton(text="😢 Грусть", callback_data="topic_грусть")],
        [InlineKeyboardButton(text="💔 Отношения", callback_data="topic_отношения")],
        [InlineKeyboardButton(text="😴 Сон", callback_data="topic_сон")],
        [InlineKeyboardButton(text="🌱 Просто поддержка", callback_data="topic_поддержка")],
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="topic_skip")],
    ])

def get_morning_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Да, в 9:00", callback_data="morning_yes_9")],
        [InlineKeyboardButton(text="☀️ Да, в 8:00", callback_data="morning_yes_8")],
        [InlineKeyboardButton(text="🌙 Да, в 10:00", callback_data="morning_yes_10")],
        [InlineKeyboardButton(text="🚫 Нет, спасибо", callback_data="morning_no")],
    ])

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😰 Мне тревожно", callback_data="quick_тревожно")],
        [InlineKeyboardButton(text="😢 Мне грустно", callback_data="quick_грустно")],
        [InlineKeyboardButton(text="😠 Я злюсь", callback_data="quick_злюсь")],
        [InlineKeyboardButton(text="😴 Не могу уснуть", callback_data="quick_сон")],
        [InlineKeyboardButton(text="💔 Отношения", callback_data="quick_отношения")],
        [InlineKeyboardButton(text="🆘 Нужна помощь", callback_data="quick_кризис")],
    ])

def get_mood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"mood_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text=str(i), callback_data=f"mood_{i}") for i in range(6, 11)],
    ])

# ===== УПРАЖНЕНИЯ =====
EXERCISES = {
    "breath": "🌬 Дыхание 4-4-4\n\nВдох — 4 сек\nЗадержка — 4 сек\nВыдох — 4 сек\n\nПовтори 5 раз. Как ты сейчас?",
    "ground": "🌳 Заземление 5-4-3-2-1\n\nНазови:\n• 5 вещей, которые видишь\n• 4 звука\n• 3 предмета, которых можешь коснуться\n• 2 запаха\n• 1 вкус\n\nКак ощущения?",
    "body": "🧘 Сканирование тела\n\nМедленно переводи внимание: стопы → голени → бёдра → живот → грудь → руки → плечи → шея → лицо.\n\nГде напряжение — «подыши» туда.",
    "relax": "💪 Прогрессивная релаксация\n\nНапряги и расслабь: кулаки, плечи, лицо, живот, ноги.\n\nПовтори 2-3 раза.",
}

# ===== КОМАНДЫ =====

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    HISTORY[message.chat.id].clear()
    ONBOARDED.discard(message.chat.id)
    USER_PROFILES.pop(message.chat.id, None)
    await message.answer(
        "Привет! Меня зовут Бот поддержки 💙\n\n"
        "Я здесь, чтобы выслушать — без осуждения и оценок.\n\n"
        "Давай познакомимся. Как тебя зовут? (можно имя или ник)"
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(
        "📖 Что я умею:\n\n"
        "🎤 Голосовые — расшифрую\n"
        "🌅 /утро — утренние сообщения\n"
        "🌬 /успокоиться — дыхание\n"
        "🌳 /заземлиться — 5-4-3-2-1\n"
        "🧘 /тело — сканирование\n"
        "💪 /релакс — прогрессивная релаксация\n"
        "📊 /настроение — отметить\n"
        "📈 /статистика — график\n"
        "👤 /profile — мой профиль\n"
        "⏰ /напомни ЧЧ:ММ текст\n"
        "🧹 /reset — очистить историю\n\n"
        "📞 Телефон доверия: 8-800-2000-122"
    )

@dp.message(Command("profile"))
async def profile_cmd(message: types.Message):
    chat_id = message.chat.id
    p = USER_PROFILES.get(chat_id, {})
    if not p:
        await message.answer("Я пока ничего о тебе не знаю. Напиши /start, чтобы познакомиться.")
        return
    age_names = {"teen": "13–17", "young": "18–25", "adult": "26–45", "older": "46+", "unknown": "не указан"}
    style_names = {"soft": "мягко", "direct": "прямо", "humor": "с юмором"}
    text = (
        f"👤 Твой профиль:\n\n"
        f"Имя: {p.get('name', 'не указано')}\n"
        f"Возраст: {age_names.get(p.get('age_group', 'unknown'), '—')}\n"
        f"Стиль: {style_names.get(p.get('style', 'soft'), '—')}\n"
        f"Тема: {p.get('topic', '—')}\n\n"
        f"Чтобы начать заново — /start"
    )
    await message.answer(text)

@dp.message(Command("утро"))
async def morning_cmd(message: types.Message):
    await message.answer("🌅 Хочешь получать тёплое сообщение по утрам?", reply_markup=get_morning_keyboard())

@dp.message(Command("утро_выкл"))
async def morning_off_cmd(message: types.Message):
    await message.answer("Хорошо, утренние выключены 🌙")

@dp.message(Command("reset"))
async def reset_cmd(message: types.Message):
    HISTORY[message.chat.id].clear()
    await message.answer("Начнём с чистого листа. О чём поговорим?", reply_markup=get_main_keyboard())

@dp.message(Command("stop"))
async def stop_cmd(message: types.Message):
    await message.answer(random.choice(FAREWELLS))

@dp.message(Command("успокоиться"))
async def breathing_cmd(message: types.Message):
    await message.answer(EXERCISES["breath"])

@dp.message(Command("заземлиться"))
async def grounding_cmd(message: types.Message):
    await message.answer(EXERCISES["ground"])

@dp.message(Command("тело"))
async def body_cmd(message: types.Message):
    await message.answer(EXERCISES["body"])

@dp.message(Command("релакс"))
async def relax_cmd(message: types.Message):
    await message.answer(EXERCISES["relax"])

@dp.message(Command("настроение"))
async def mood_cmd(message: types.Message):
    await message.answer("Оцени настроение от 1 до 10:", reply_markup=get_mood_keyboard())

@dp.message(Command("статистика"))
async def stats_cmd(message: types.Message):
    log = MOOD_LOG.get(message.chat.id, [])
    if not log:
        await message.answer("Ты пока не отмечал. Напиши /настроение.")
        return
    last = log[-10:]
    lines = [f"📅 {d}: {'⭐' * s} ({s}/10)" for d, s in last]
    avg = sum(s for _, s in last) / len(last)
    await message.answer("📈 Настроение:\n\n" + "\n".join(lines) + f"\n\nСреднее: {avg:.1f}/10")

@dp.message(Command("напомни"))
async def remind_cmd(message: types.Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: `/напомни 20:30 выпить воды`")
        return
    try:
        h, m = map(int, parts[1].split(":"))
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        REMINDERS.append((message.chat.id, target.timestamp(), parts[2]))
        await message.answer(f"⏰ Напомню в {parts[1]}")
    except Exception:
        await message.answer("Не понял время. Формат: ЧЧ:ММ")

# ===== CALLBACK =====

@dp.callback_query()
async def on_callback(callback: CallbackQuery):
    data = callback.data
    chat_id = callback.message.chat.id
    await callback.answer()

    # Онбординг: возраст
    if data.startswith("age_"):
        age = data.replace("age_", "")
        USER_PROFILES.setdefault(chat_id, {})["age_group"] = age
        await callback.message.answer("Отлично. Как ты предпочитаешь общаться?", reply_markup=get_style_keyboard())
        return

    # Онбординг: стиль
    if data.startswith("style_"):
        style = data.replace("style_", "")
        USER_PROFILES.setdefault(chat_id, {})["style"] = style
        ONBOARDED.add(chat_id)
        await callback.message.answer("Что чаще всего тебя беспокоит?", reply_markup=get_topics_keyboard())
        return

    # Онбординг: тема
    if data.startswith("topic_"):
        topic = data.replace("topic_", "")
        if topic != "skip":
            USER_PROFILES.setdefault(chat_id, {})["topic"] = topic
        await callback.message.answer(
            "Спасибо! Я всё запомнил(а).\n\n"
            "⚠️ Я — ИИ, а не живой психолог. Если будет плохо — 8-800-2000-122.\n\n"
            "Как ты сейчас?",
            reply_markup=get_main_keyboard()
        )
        await callback.message.answer("И ещё: хочешь получать тёплое сообщение по утрам?", reply_markup=get_morning_keyboard())
        return

    # Утренние
    if data.startswith("morning_yes_"):
        t = data.replace("morning_yes_", "") + ":00"
        USER_PROFILES.setdefault(chat_id, {})["morning"] = t
        await callback.message.answer(f"🌅 Отлично! Буду писать в {t}.")
        return
    if data == "morning_no":
        await callback.message.answer("Хорошо 🌙")
        return

    # Настроение
    if data.startswith("mood_"):
        score = int(data.replace("mood_", ""))
        today = datetime.now().strftime("%d.%m")
        MOOD_LOG[chat_id].append((today, score))
        await callback.message.answer(f"Записал: {score}/10 💙")
        return

    # Кризис
    if data == "quick_кризис":
        await callback.message.answer(CRISIS_REPLY)
        return

    # Упражнения
    if data.startswith("ex_"):
        key = data.replace("ex_", "")
        if key in EXERCISES:
            await callback.message.answer(EXERCISES[key])
        return

    prompts = {
        "quick_тревожно": "Мне тревожно. Помоги разобраться.",
        "quick_грустно": "Мне грустно. Хочу поговорить.",
        "quick_злюсь": "Я злюсь. Помоги понять почему.",
        "quick_сон": "Не могу уснуть. Что делать?",
        "quick_отношения": "Проблемы в отношениях.",
    }
    await process_message(callback.message, prompts.get(data, "Мне нужна поддержка."))

# ===== ОСНОВНАЯ ЛОГИКА =====

async def process_message(message: types.Message, text: str):
    chat_id = message.chat.id

    if is_crisis(text):
        print(f"[CRISIS]")
        await message.answer(CRISIS_REPLY)
        return

    add_to_history(chat_id, "user", text)
    await bot.send_chat_action(chat_id, "typing")

    # Собираем персональный промпт
    p = USER_PROFILES.get(chat_id, {})
    system_prompt = get_system_prompt(p.get("age_group", "unknown"), p.get("style", "soft"))
    name = p.get("name", "")
    if name:
        system_prompt += f"\n\nИмя пользователя: {name}."

    messages = [{"role": "system", "content": system_prompt}] + HISTORY[chat_id]

    last_error = None
    for model_name in FREE_MODELS:
        try:
            print(f"[AI] {model_name}")
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=600
            )
            answer = response.choices[0].message.content
            add_to_history(chat_id, "assistant", answer)
            await message.answer(answer)
            return
        except Exception as e:
            print(f"[AI] {model_name} упала: {type(e).__name__}")
            last_error = e
            continue

    print(f"[ERROR] все упали: {last_error}")
    await message.answer(random.choice(ERROR_REPLIES))

# ===== ГОЛОСОВЫЕ =====

async def transcribe_voice(file_path: str) -> str:
    import base64
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    response = client.chat.completions.create(
        model=VOICE_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Расшифруй голосовое дословно на русском. Верни только текст."},
                {"type": "input_audio", "input_audio": {"data": b64, "format": "ogg"}},
            ],
        }],
        max_tokens=500
    )
    return response.choices[0].message.content.strip()

@dp.message(lambda m: m.voice is not None)
async def voice_handler(message: types.Message):
    chat_id = message.chat.id
    await bot.send_chat_action(chat_id, "typing")
    try:
        file = await bot.get_file(message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await bot.download_file(file.file_path, tmp.name)
            tmp_path = tmp.name
        text = await transcribe_voice(tmp_path)
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        if not text:
            await message.answer("Не смог разобрать. Попробуй ещё или напиши текстом.")
            return
        await message.answer(f"🎤 Я услышал: _{text}_")
        await process_message(message, text)
    except Exception as e:
        print(f"[VOICE] {type(e).__name__}: {e}")
        await message.answer("Не получилось расшифровать. Напиши текстом.")

# ===== ТЕКСТ =====

@dp.message()
async def chat_handler(message: types.Message):
    if not message.text:
        return
    chat_id = message.chat.id
    if chat_id not in ONBOARDED:
        if len(HISTORY[chat_id]) == 0:
            # Первое сообщение — это имя
            name = message.text.strip()[:50]
            USER_PROFILES.setdefault(chat_id, {})["name"] = name
            HISTORY[chat_id].append({"role": "system", "content": f"Имя: {name}"})
            ONBOARDED.add(chat_id)
            await message.answer(
                f"Приятно познакомиться, {name}! 🌿\n\n"
                f"Сколько тебе лет? (это поможет мне общаться с тобой комфортнее)\n"
                f"Можешь пропустить, если не хочешь говорить.",
                reply_markup=get_age_keyboard()
            )
            return
    print(f"[MSG] {message.text[:50]}")
    await process_message(message, message.text)

# ===== ПЛАНИРОВЩИК =====

async def scheduler_worker():
    last_check = ""
    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        check_key = f"{now.strftime('%d.%m.%Y')}_{current_time}"

        if check_key != last_check:
            for chat_id, profile in list(USER_PROFILES.items()):
                if profile.get("morning") == current_time:
                    try:
                        msgs = [
                            "Доброе утро 🌅 Как ты?",
                            "Утро 💙 Я рядом.",
                            "Привет 🌿 Как спалось?",
                            "Доброе утро ✨ Как настроение?",
                        ]
                        await bot.send_message(chat_id, random.choice(msgs))
                        print(f"[MORNING] {chat_id}")
                    except Exception as e:
                        print(f"[MORNING] ошибка: {e}")
            last_check = check_key

        # Напоминания
        now_ts = now.timestamp()
        to_send = [r for r in REMINDERS if r[1] <= now_ts]
        REMINDERS[:] = [r for r in REMINDERS if r[1] > now_ts]
        for chat_id, _, text in to_send:
            try:
                await bot.send_message(chat_id, f"⏰ Напоминание: {text}")
            except Exception as e:
                print(f"[REMIND] {e}")

        await asyncio.sleep(30)

# ===== ВЕБ-СЕРВЕР =====

async def handle(request):
    return web.Response(text="Bot is running!")

async def main():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"=== ВЕБ-СЕРВЕР НА ПОРТУ {port} ===")

    asyncio.create_task(scheduler_worker())
    print("=== ПЛАНИРОВЩИК ЗАПУЩЕН ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
