import os, asyncio, random, tempfile, re, base64
from datetime import datetime
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from openai import OpenAI
from aiohttp import web
import aiohttp as aio

print("=== START ===")

TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

print(f"GROQ key: {'yes' if GROQ_KEY else 'NO'}")
print(f"OpenRouter key: {'yes' if OPENROUTER_KEY else 'NO'}")
print(f"SerpAPI key: {'yes' if SERPAPI_KEY else 'NO'}")

# ===== ДВА ПРОВАЙДЕРА =====
groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY,
) if GROQ_KEY else None

openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY,
) if OPENROUTER_KEY else None

bot = Bot(token=TOKEN)
dp = Dispatcher()

HISTORY = defaultdict(list)
PROFILES = {}
ONBOARDED = set()

GROQ_MODELS = []
OPENROUTER_MODELS = []

VOICE_MODEL = "whisper-large-v3"
VISION_MODEL_GROQ = "llama-3.2-90b-vision-preview"
VISION_MODEL_OR = "google/gemini-2.0-flash-exp:free"

# ===== ЗАГРУЗКА МОДЕЛЕЙ =====
def load_groq_models():
    if not groq_client:
        return []
    try:
        r = groq_client.models.list()
        models = [m.id for m in r.data if not any(x in m.id for x in ["whisper", "tts", "embedding", "guard"])]
        print(f"[GROQ MODELS] {len(models)}: {models}")
        return models
    except Exception as e:
        print(f"[GROQ MODELS ERR] {type(e).__name__}")
        return []

def load_openrouter_models():
    if not openrouter_client:
        return []
    try:
        r = openrouter_client.models.list()
        models = [m.id for m in r.data if ":free" in m.id]
        print(f"[OR MODELS] {len(models)}")
        return models
    except Exception as e:
        print(f"[OR MODELS ERR] {type(e).__name__}")
        return []

CRISIS_WORDS = [
    "умираю", "умереть", "умру", "смерть", "суицид", "самоубий",
    "не хочу жить", "хочу умереть", "убить себя", "покончить",
    "резать", "порезы", "повеситься", "передозировка",
    "прощай", "нет выхода", "всё кончено", "хочу исчезнуть",
]

CRISIS_REPLY = """Я слышу тебя. То, что ты сейчас чувствуешь — очень тяжело, и ты не один.

Пожалуйста, позвони туда, где помогут живые люди:
📞 8-800-2000-122 — телефон доверия (круглосуточно, анонимно)
📞 8-495-989-50-50 — психологическая помощь
📞 8-800-333-44-34 — Всероссийская линия
📞 112 — экстренные службы

Ты важен. Не оставайся с этим один."""

def is_crisis(t):
    t = t.lower()
    return any(w in t for w in CRISIS_WORDS)

def add_hist(cid, role, content):
    HISTORY[cid].append({"role": role, "content": content})
    if len(HISTORY[cid]) > 40:
        HISTORY[cid] = HISTORY[cid][-40:]

def parse_age(text: str):
    text = text.strip().lower()
    numbers = re.findall(r'\d+', text)
    if not numbers:
        words = {
            "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
            "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
            "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
            "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40,
            "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
        }
        for w, n in words.items():
            if w in text:
                return n
        return None
    age = int(numbers[0])
    if 1 <= age <= 120:
        return age
    return None

def get_age_group(age: int) -> str:
    if age < 13: return "child"
    elif age < 18: return "teen"
    elif age < 26: return "young"
    elif age < 46: return "adult"
    elif age < 61: return "middle"
    else: return "older"

def sys_prompt(age=None, style="soft", mode=None):
    base = "Ты — умный ассистент. Не ставь диагнозы. Помни контекст."

    if mode == "school":
        base = ("Ты — умный помощник по школьным предметам. Решай задачи, объясняй правила. "
                "Объясняй понятно, как хороший учитель. Если задача — покажи решение пошагово.")
    elif mode == "explain":
        base = "Ты — понятный объяснятель. Объясни сложное просто, с примерами."
    elif mode == "translate":
        base = "Ты — переводчик. Переводи точно, сохраняя смысл."
    elif mode == "ideas":
        base = "Ты — генератор идей. Дай 5-7 разных вариантов."
    elif mode == "plan":
        base = "Ты — составитель планов. Дай пошаговый план."
    elif mode == "proscons":
        base = "Ты — аналитик. Разбери ситуацию по плюсам и минусам."
    elif mode == "coach":
        base = "Ты — коуч. НЕ давай советов. Задавай глубокие вопросы."
    elif mode == "philosopher":
        base = "Ты — философ. Размышляй глубоко, без пафоса."
    elif mode == "friend":
        base = "Ты — тёплый, поддерживающий друг."
    elif mode == "summary":
        base = "Ты — резюмирующий. Дай краткое резюме диалога."
    elif style == "wise":
        base = ("Ты — умный, объективный и конструктивный ассистент. "
                "Помогай разобраться. Говори прямо, по делу, коротко. "
                "Будь честным. Предлагай конкретные шаги.")
    elif style == "direct":
        base = "Ты — ассистент. Прямо, по делу, без воды."
    elif style == "humor":
        base = "Ты — ассистент с лёгким юмором."
    else:
        base = "Ты — эмпатичный ассистент-психолог. Тепло, по-человечески."

    if age is not None:
        group = get_age_group(age)
        adds = {
            "child": f" Пользователю {age} лет — ребёнок. Простые слова.",
            "teen": f" Пользователю {age} лет — подросток. Простой язык.",
            "young": f" Пользователю {age} лет — 18-25. На равных.",
            "adult": f" Пользователю {age} лет — взрослый. Уважительно.",
            "middle": f" Пользователю {age} лет. Уважительно.",
            "older": f" Пользователю {age} лет — старший. Уважительно, не спеша.",
        }
        base += adds.get(group, "")
    return base

def kb_style():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Мягко", callback_data="style_soft"),
         InlineKeyboardButton(text="💬 Прямо", callback_data="style_direct")],
        [InlineKeyboardButton(text="✨ С юмором", callback_data="style_humor")],
        [InlineKeyboardButton(text="🧠 Мудрый", callback_data="style_wise")],
    ])

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😰 Тревожно", callback_data="q_тревожно"),
         InlineKeyboardButton(text="😢 Грустно", callback_data="q_грустно")],
        [InlineKeyboardButton(text="😠 Злюсь", callback_data="q_злюсь"),
         InlineKeyboardButton(text="😴 Не уснуть", callback_data="q_сон")],
        [InlineKeyboardButton(text="💔 Отношения", callback_data="q_отношения"),
         InlineKeyboardButton(text="🆘 Помощь", callback_data="q_кризис")],
    ])

EX = {
    "breath": "🌬 Дыхание 4-4-4\n\nВдох 4 сек → задержка 4 → выдох 4. Повтори 5 раз. Как ты?",
    "ground": "🌳 Заземление 5-4-3-2-1\n\n5 видишь, 4 слышишь, 3 коснёшься, 2 запаха, 1 вкус.",
    "body": "🧘 Сканирование тела\n\nПереводи внимание: стопы → ноги → живот → грудь → руки → шея → лицо.",
    "relax": "💪 Релаксация\n\nНапряги и расслабь: кулаки, плечи, лицо, живот, ноги.",
}

# ===== УМНЫЙ ЗАПРОС С ДВУМЯ ПРОВАЙДЕРАМИ =====
def try_models(messages, max_tokens=700):
    """Пробует модели сначала Groq, потом OpenRouter."""
    # Сначала Groq
    for model in GROQ_MODELS:
        try:
            r = groq_client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            print(f"[OK GROQ] {model}")
            return r.choices[0].message.content
        except Exception as e:
            print(f"[GROQ] {model}: {type(e).__name__}")

    # Потом OpenRouter
    for model in OPENROUTER_MODELS[:15]:
        try:
            r = openrouter_client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            print(f"[OK OR] {model}")
            return r.choices[0].message.content
        except Exception as e:
            print(f"[OR] {model}: {type(e).__name__}")

    return None

# ===== ПОИСК =====
async def web_search(query: str):
    if not SERPAPI_KEY:
        return None
    try:
        async with aio.ClientSession() as session:
            async with session.get(
                "https://serpapi.com/search",
                params={"q": query, "api_key": SERPAPI_KEY, "hl": "ru", "gl": "ru"}
            ) as resp:
                data = await resp.json()
                results = []
                if "answer_box" in data:
                    results.append(str(data["answer_box"].get("answer", "")))
                for r in data.get("organic_results", [])[:3]:
                    results.append(f"{r.get('title', '')}: {r.get('snippet', '')}")
                return "\n".join(results) if results else None
    except Exception as e:
        print(f"[SEARCH] {e}")
        return None

# ===== КОМАНДЫ =====

@dp.message(Command("start"))
async def start(m: types.Message):
    HISTORY[m.chat.id].clear()
    ONBOARDED.discard(m.chat.id)
    PROFILES.pop(m.chat.id, None)
    await m.answer("Привет! Я Бот поддержки 💙\n\nЯ здесь, чтобы выслушать. Как тебя зовут?")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    await m.answer(
        "💡 Что я умею:\n\n"
        "📸 Отправь фото задачи или текста — распознаю\n"
        "🎤 Голосовые — расшифрую\n"
        "🆘 Если плохо — дам телефон доверия\n\n"
        "🎓 Школа:\n"
        "/школа — режим помощи с учёбой\n"
        "/задача [текст] — решу задачу\n"
        "/поиск [запрос] — поиск в интернете\n\n"
        "🎓 Инструменты:\n"
        "/объясни, /перевод, /идеи, /план, /плюсы_минусы, /резюме\n\n"
        "🎭 Режимы: /коуч, /философ, /друг, /wise, /soft\n\n"
        "🌬 /успокоиться, /заземлиться, /тело, /релакс\n\n"
        "👤 /profile, 🧹 /reset\n\n"
        "📞 8-800-2000-122\n"
        "⚠️ Я не заменяю живого специалиста."
    )

@dp.message(Command("школа"))
async def school_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["mode"] = "school"
    await m.answer("🎓 Режим «Школа» включён. Напиши вопрос или отправь фото задания.")

@dp.message(Command("задача"))
async def task_cmd(m: types.Message):
    text = m.text.replace("/задача", "").strip()
    if not text:
        await m.answer("Напиши задачу. Например: `/задача 2x + 5 = 15`")
        return
    await run_tool(m, text, "school")

@dp.message(Command("поиск"))
async def search_cmd(m: types.Message):
    query = m.text.replace("/поиск", "").strip()
    if not query:
        await m.answer("Напиши, что искать.")
        return
    if not SERPAPI_KEY:
        await m.answer("⚠️ Поиск не настроен (нужен SERPAPI_KEY).")
        return
    await bot.send_chat_action(m.chat.id, "typing")
    results = await web_search(query)
    if not results:
        await m.answer("Ничего не нашёл.")
        return
    cid = m.chat.id
    sysmsg = sys_prompt(PROFILES.get(cid, {}).get("age"), "soft")
    msgs = [
        {"role": "system", "content": sysmsg},
        {"role": "user", "content": f"Вопрос: {query}\n\nНашлось в интернете:\n{results}\n\nОтветь кратко на основе этой информации."}
    ]
    ans = try_models(msgs, 500)
    if ans:
        await m.answer(f"🔍 *{query}*\n\n{ans}\n\n_Источник: поиск в интернете_", parse_mode="Markdown")
    else:
        await m.answer(f"🔍 Нашёл:\n\n{results}")

@dp.message(Command("объясни"))
async def explain_cmd(m: types.Message):
    t = m.text.replace("/объясни", "").strip()
    if not t: await m.answer("Что объяснить?"); return
    await run_tool(m, t, "explain")

@dp.message(Command("перевод"))
async def translate_cmd(m: types.Message):
    t = m.text.replace("/перевод", "").strip()
    if not t: await m.answer("Что перевести?"); return
    await run_tool(m, t, "translate")

@dp.message(Command("идеи"))
async def ideas_cmd(m: types.Message):
    t = m.text.replace("/идеи", "").strip()
    if not t: await m.answer("Тема?"); return
    await run_tool(m, t, "ideas")

@dp.message(Command("план"))
async def plan_cmd(m: types.Message):
    t = m.text.replace("/план", "").strip()
    if not t: await m.answer("Цель?"); return
    await run_tool(m, t, "plan")

@dp.message(Command("плюсы_минусы"))
async def proscons_cmd(m: types.Message):
    t = m.text.replace("/плюсы_минусы", "").strip()
    if not t: await m.answer("Ситуация?"); return
    await run_tool(m, t, "proscons")

@dp.message(Command("резюме"))
async def summary_cmd(m: types.Message):
    cid = m.chat.id
    if len(HISTORY[cid]) < 4:
        await m.answer("Пока мало сообщений.")
        return
    await run_tool(m, "Сделай краткое резюме диалога: о чём говорили, что важного, что дальше.", "summary")

@dp.message(Command("коуч"))
async def coach_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["mode"] = "coach"
    await m.answer("🎓 Режим «Коуч» включён. Задаю вопросы, не даю советов.")

@dp.message(Command("философ"))
async def philosopher_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["mode"] = "philosopher"
    await m.answer("🌌 Режим «Философ» включён.")

@dp.message(Command("друг"))
async def friend_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["mode"] = "friend"
    await m.answer("🤍 Режим «Друг» включён. Я рядом.")

@dp.message(Command("wise"))
async def wise_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["style"] = "wise"
    PROFILES.setdefault(m.chat.id, {})["mode"] = None
    await m.answer("🧠 Режим «Мудрый» включён.")

@dp.message(Command("soft"))
async def soft_cmd(m: types.Message):
    PROFILES.setdefault(m.chat.id, {})["style"] = "soft"
    PROFILES.setdefault(m.chat.id, {})["mode"] = None
    await m.answer("🤍 Мягкий режим включён.")

@dp.message(Command("profile"))
async def profile(m: types.Message):
    p = PROFILES.get(m.chat.id, {})
    if not p:
        await m.answer("Пока ничего не знаю. /start"); return
    styles = {"soft": "мягко", "direct": "прямо", "humor": "с юмором", "wise": "мудрый"}
    age = p.get("age", "—")
    await m.answer(f"👤 Имя: {p.get('name', '—')}\nВозраст: {age}\nСтиль: {styles.get(p.get('style', 'soft'), '—')}\nРежим: {p.get('mode') or 'обычный'}")

@dp.message(Command("reset"))
async def reset(m: types.Message):
    HISTORY[m.chat.id].clear()
    await m.answer("Начнём заново. О чём поговорим?", reply_markup=kb_main())

@dp.message(Command("успокоиться"))
async def ex1(m: types.Message): await m.answer(EX["breath"])

@dp.message(Command("заземлиться"))
async def ex2(m: types.Message): await m.answer(EX["ground"])

@dp.message(Command("тело"))
async def ex3(m: types.Message): await m.answer(EX["body"])

@dp.message(Command("релакс"))
async def ex4(m: types.Message): await m.answer(EX["relax"])

@dp.callback_query()
async def cb(c: CallbackQuery):
    d = c.data
    cid = c.message.chat.id
    await c.answer()

    if d.startswith("style_"):
        PROFILES.setdefault(cid, {})["style"] = d.replace("style_", "")
        PROFILES.setdefault(cid, {})["mode"] = None
        ONBOARDED.add(cid)
        await c.message.answer(
            "Спасибо! Я всё запомнил 🌿\n\n"
            "💡 Что я умею:\n"
            "• 📸 Отправь фото задачи — распознаю и решу\n"
            "• 🎤 Голосовые\n"
            "• 🎓 /школа, /задача, /поиск\n"
            "• /объясни, /перевод, /идеи, /план\n"
            "• 🎭 /коуч, /философ, /друг, /wise\n"
            "• 🌬 /успокоиться, /заземлиться\n\n"
            "⚠️ Я — ИИ, не живой психолог. Если плохо — 8-800-2000-122.\n\n"
            "Как ты сейчас?"
        )
        return

    if d == "q_кризис":
        await c.message.answer(CRISIS_REPLY)
        return

    prompts = {
        "q_тревожно": "Мне тревожно.", "q_грустно": "Мне грустно.",
        "q_злюсь": "Я злюсь.", "q_сон": "Не могу уснуть.",
        "q_отношения": "Проблемы в отношениях.",
    }
    await process(c.message, prompts.get(d, "Мне нужна поддержка."))

async def run_tool(m: types.Message, text: str, tool: str):
    cid = m.chat.id
    await bot.send_chat_action(cid, "typing")
    p = PROFILES.get(cid, {})
    sysmsg = sys_prompt(p.get("age"), p.get("style", "soft"), tool)
    msgs = [{"role": "system", "content": sysmsg}]
    if tool == "summary":
        msgs += HISTORY[cid][-20:]
        msgs.append({"role": "user", "content": text})
    else:
        msgs.append({"role": "user", "content": text})
    ans = try_models(msgs, 600)
    if ans:
        await m.answer(ans)
    else:
        await m.answer("Не получилось. Попробуй ещё раз.")

async def process(m: types.Message, text: str):
    cid = m.chat.id
    if is_crisis(text):
        await m.answer(CRISIS_REPLY)
        return
    add_hist(cid, "user", text)
    await bot.send_chat_action(cid, "typing")
    p = PROFILES.get(cid, {})
    sysmsg = sys_prompt(p.get("age"), p.get("style", "soft"), p.get("mode"))
    if p.get("name"):
        sysmsg += f" Имя: {p['name']}."
    msgs = [{"role": "system", "content": sysmsg}] + HISTORY[cid]
    max_tok = 350 if p.get("style") == "wise" else 700
    ans = try_models(msgs, max_tok)
    if ans:
        add_hist(cid, "assistant", ans)
        await m.answer(ans)
    else:
        await m.answer("Извини, задумался. Попробуй через минуту.\n\nЕсли плохо — 8-800-2000-122")

# ===== ФОТО =====
async def analyze_image(path: str, caption: str = ""):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    prompt = "Что на картинке? Если задача — реши её. Если текст — распознай и объясни."
    if caption:
        prompt = f"Пользователь написал: {caption}\n\n{prompt}"

    # Пробуем Groq Vision
    try:
        r = groq_client.chat.completions.create(
            model=VISION_MODEL_GROQ,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]}],
            max_tokens=800
        )
        print(f"[OK VISION GROQ]")
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[VISION GROQ] {type(e).__name__}")

    # Пробуем OpenRouter Vision
    try:
        r = openrouter_client.chat.completions.create(
            model=VISION_MODEL_OR,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]}],
            max_tokens=800
        )
        print(f"[OK VISION OR]")
        return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"[VISION OR] {type(e).__name__}")

    return None

@dp.message(lambda m: m.photo is not None)
async def photo_handler(m: types.Message):
    cid = m.chat.id
    await bot.send_chat_action(cid, "typing")
    try:
        photo = m.photo[-1]
        f = await bot.get_file(photo.file_id)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            await bot.download_file(f.file_path, tmp.name)
            p = tmp.name
        ans = await analyze_image(p, m.caption or "")
        try: os.unlink(p)
        except: pass
        if ans:
            await m.answer(f"📸 {ans}")
        else:
            await m.answer("Не получилось распознать фото.")
    except Exception as e:
        print(f"[PHOTO] {e}")
        await m.answer("Ошибка с фото.")

@dp.message(lambda m: m.voice is not None)
async def voice(m: types.Message):
    cid = m.chat.id
    await bot.send_chat_action(cid, "typing")
    try:
        f = await bot.get_file(m.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await bot.download_file(f.file_path, tmp.name)
            p = tmp.name
        with open(p, "rb") as f:
            r = groq_client.audio.transcriptions.create(model=VOICE_MODEL, file=f)
        t = r.text.strip()
        try: os.unlink(p)
        except: pass
        if not t:
            await m.answer("Не разобрал.")
            return
        await m.answer(f"🎤 Я услышал: _{t}_")
        await process(m, t)
    except Exception as e:
        print(f"[VOICE] {e}")
        await m.answer("Не получилось. Напиши текстом.")

@dp.message()
async def chat(m: types.Message):
    if not m.text:
        return
    cid = m.chat.id
    p = PROFILES.setdefault(cid, {})

    if cid not in ONBOARDED and len(HISTORY[cid]) == 0:
        name = m.text.strip()[:50]
        p["name"] = name
        HISTORY[cid].append({"role": "system", "content": f"Имя: {name}"})
        ONBOARDED.add(cid)
        await m.answer(f"Приятно познакомиться, {name}! 🌿\n\nСколько тебе лет? Напиши цифрой.")
        return

    if "age" not in p:
        age = parse_age(m.text)
        if age is None:
            await m.answer("Не понял. Напиши цифрой: 15, 25, 40, 65.")
            return
        p["age"] = age
        group = get_age_group(age)
        replies = {
            "child": "Понял! Буду говорить просто 🌟",
            "teen": "Понял! Буду общаться по-дружески 🌿",
            "young": "Понял! Будем на равных 💬",
            "adult": "Понял, спасибо 🌿",
            "middle": "Понял, спасибо 🌿",
            "older": "Понял. Уважительно, не спеша 🌿",
        }
        await m.answer(f"{replies.get(group, 'Спасибо!')}\n\nКак предпочитаешь общаться?", reply_markup=kb_style())
        return

    print(f"[MSG] {m.text[:50]}")
    await process(m, m.text)

async def handle(req):
    return web.Response(text="Bot is running!")

async def main():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"=== WEB SERVER ON PORT {port} ===")

    global GROQ_MODELS, OPENROUTER_MODELS
    GROQ_MODELS = load_groq_models()
    OPENROUTER_MODELS = load_openrouter_models()
    print(f"=== GROQ: {len(GROQ_MODELS)}, OpenRouter: {len(OPENROUTER_MODELS)} ===")

    print("=== ЖДУ 15 СЕКУНД ===")
    await asyncio.sleep(15)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("=== ВЕБХУК УДАЛЁН ===")
    except Exception as e:
        print(f"[WEBHOOK] {e}")
    print("=== СЛУШАЮ TELEGRAM ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
