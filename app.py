import os, asyncio, random, json, tempfile
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from openai import OpenAI
from aiohttp import web

print("=== START ===")

TOKEN = os.getenv("TELEGRAM_TOKEN")
KEY = os.getenv("OPENROUTER_API_KEY")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher()

HISTORY = defaultdict(list)
MOOD_LOG = defaultdict(list)
REMINDERS = []
PROFILES = {}
ONBOARDED = set()

MODELS = [
    "nvidia/nemotron-3-super:free",
    "qwen/qwen-3-8-27b:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]
VOICE_MODEL = "google/gemini-2.0-flash-exp:free"

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
    if len(HISTORY[cid]) > 20:
        HISTORY[cid] = HISTORY[cid][-20:]

def sys_prompt(age="unknown", style="soft"):
    base = "Ты — эмпатичный ассистент-психолог. Не ставь диагнозы. Отвечай тепло, по-человечески, кратко. Помни контекст."
    extra = {
        "teen": " Пользователь — подросток. Говори как старший друг, без нравоучений.",
        "young": " Пользователь — 18-25 лет. На равных, современно.",
        "adult": " Пользователь — взрослый. Уважительно, по-взрослому.",
        "older": " Пользователь — старшего возраста. Тепло, с уважением к опыту.",
    }.get(age, "")
    style_extra = {
        "soft": " Мягко и бережно.",
        "direct": " Прямо и по делу.",
        "humor": " Легко, с юмором.",
    }.get(style, "")
    return base + extra + style_extra

def kb_age():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="13–17", callback_data="age_teen")],
        [InlineKeyboardButton(text="18–25", callback_data="age_young")],
        [InlineKeyboardButton(text="26–45", callback_data="age_adult")],
        [InlineKeyboardButton(text="46+", callback_data="age_older")],
        [InlineKeyboardButton(text="Пропустить", callback_data="age_skip")],
    ])

def kb_style():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Мягко", callback_data="style_soft")],
        [InlineKeyboardButton(text="💬 Прямо", callback_data="style_direct")],
        [InlineKeyboardButton(text="✨ С юмором", callback_data="style_humor")],
    ])

def kb_topics():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😰 Тревога", callback_data="topic_тревога")],
        [InlineKeyboardButton(text="😢 Грусть", callback_data="topic_грусть")],
        [InlineKeyboardButton(text="💔 Отношения", callback_data="topic_отношения")],
        [InlineKeyboardButton(text="😴 Сон", callback_data="topic_сон")],
        [InlineKeyboardButton(text="🌱 Поддержка", callback_data="topic_поддержка")],
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="topic_skip")],
    ])

def kb_morning():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 9:00", callback_data="morning_9")],
        [InlineKeyboardButton(text="☀️ 8:00", callback_data="morning_8")],
        [InlineKeyboardButton(text="🌙 10:00", callback_data="morning_10")],
        [InlineKeyboardButton(text="🚫 Нет", callback_data="morning_no")],
    ])

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😰 Тревожно", callback_data="quick_тревожно")],
        [InlineKeyboardButton(text="😢 Грустно", callback_data="quick_грустно")],
        [InlineKeyboardButton(text="😠 Злюсь", callback_data="quick_злюсь")],
        [InlineKeyboardButton(text="😴 Не уснуть", callback_data="quick_сон")],
        [InlineKeyboardButton(text="💔 Отношения", callback_data="quick_отношения")],
        [InlineKeyboardButton(text="🆘 Помощь", callback_data="quick_кризис")],
    ])

def kb_mood():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(i), callback_data=f"mood_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text=str(i), callback_data=f"mood_{i}") for i in range(6, 11)],
    ])

EX = {
    "breath": "🌬 Дыхание 4-4-4\n\nВдох 4 сек → задержка 4 → выдох 4. Повтори 5 раз. Как ты?",
    "ground": "🌳 Заземление 5-4-3-2-1\n\n5 видишь, 4 слышишь, 3 коснёшься, 2 запаха, 1 вкус. Как ощущения?",
    "body": "🧘 Сканирование тела\n\nПереводи внимание: стопы → ноги → живот → грудь → руки → шея → лицо. Где напряжение — дыши туда.",
    "relax": "💪 Релаксация\n\nНапряги и расслабь: кулаки, плечи, лицо, живот, ноги. Повтори 2-3 раза.",
}

@dp.message(Command("start"))
async def start(m: types.Message):
    HISTORY[m.chat.id].clear()
    ONBOARDED.discard(m.chat.id)
    PROFILES.pop(m.chat.id, None)
    await m.answer("Привет! Меня зовут Бот поддержки 💙\n\nЯ здесь, чтобы выслушать. Как тебя зовут?")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    await m.answer(
        "Что умею:\n"
        "🎤 Голосовые\n🌅 /утро — утренние сообщения\n"
        "🌬 /успокоиться\n🌳 /заземлиться\n🧘 /тело\n💪 /релакс\n"
        "📊 /настроение\n📈 /статистика\n👤 /profile\n"
        "⏰ /напомни ЧЧ:ММ текст\n🧹 /reset\n\n"
        "📞 Телефон доверия: 8-800-2000-122"
    )

@dp.message(Command("profile"))
async def profile(m: types.Message):
    p = PROFILES.get(m.chat.id, {})
    if not p:
        await m.answer("Пока ничего не знаю. /start")
        return
    ages = {"teen": "13-17", "young": "18-25", "adult": "26-45", "older": "46+", "unknown": "—"}
    styles = {"soft": "мягко", "direct": "прямо", "humor": "с юмором"}
    await m.answer(
        f"👤 Имя: {p.get('name', '—')}\n"
        f"Возраст: {ages.get(p.get('age_group', 'unknown'), '—')}\n"
        f"Стиль: {styles.get(p.get('style', 'soft'), '—')}\n"
        f"Тема: {p.get('topic', '—')}"
    )

@dp.message(Command("утро"))
async def morning(m: types.Message):
    await m.answer("🌅 Хочешь тёплое сообщение по утрам?", reply_markup=kb_morning())

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

@dp.message(Command("настроение"))
async def mood(m: types.Message):
    await m.answer("Оцени настроение от 1 до 10:", reply_markup=kb_mood())

@dp.message(Command("статистика"))
async def stats(m: types.Message):
    log = MOOD_LOG.get(m.chat.id, [])
    if not log:
        await m.answer("Пока нет отметок. /настроение")
        return
    last = log[-10:]
    avg = sum(s for _, s in last) / len(last)
    text = "\n".join(f"{d}: {'⭐' * s} ({s}/10)" for d, s in last)
    await m.answer(f"📈 Настроение:\n\n{text}\n\nСреднее: {avg:.1f}/10")

@dp.message(Command("напомни"))
async def remind(m: types.Message):
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        await m.answer("Формат: /напомни 20:30 выпить воды")
        return
    try:
        h, mi = map(int, parts[1].split(":"))
        now = datetime.now()
        target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        REMINDERS.append((m.chat.id, target.timestamp(), parts[2]))
        await m.answer(f"⏰ Напомню в {parts[1]}")
    except Exception:
        await m.answer("Формат: ЧЧ:ММ")

@dp.callback_query()
async def cb(c: CallbackQuery):
    d = c.data
    cid = c.message.chat.id
    await c.answer()

    if d.startswith("age_"):
        age = d.replace("age_", "")
        PROFILES.setdefault(cid, {})["age_group"] = age
        await c.message.answer("Отлично. Как предпочитаешь общаться?", reply_markup=kb_style())
        return

    if d.startswith("style_"):
        st = d.replace("style_", "")
        PROFILES.setdefault(cid, {})["style"] = st
        ONBOARDED.add(cid)
        await c.message.answer("Что чаще беспокоит?", reply_markup=kb_topics())
        return

    if d.startswith("topic_"):
        t = d.replace("topic_", "")
        if t != "skip":
            PROFILES.setdefault(cid, {})["topic"] = t
        await c.message.answer("Спасибо! Я всё запомнил.\n\n⚠️ Я — ИИ, не живой психолог. Если плохо — 8-800-2000-122.\n\nКак ты сейчас?", reply_markup=kb_main())
        await c.message.answer("Хочешь тёплое сообщение по утрам?", reply_markup=kb_morning())
        return

    if d.startswith("morning_"):
        if d == "morning_no":
            await c.message.answer("Хорошо 🌙")
            return
        t = d.replace("morning_", "") + ":00"
        PROFILES.setdefault(cid, {})["morning"] = t
        await c.message.answer(f"🌅 Буду писать в {t}.")
        return

    if d.startswith("mood_"):
        s = int(d.replace("mood_", ""))
        MOOD_LOG[cid].append((datetime.now().strftime("%d.%m"), s))
        await c.message.answer(f"Записал: {s}/10 💙")
        return

    if d == "quick_кризис":
        await c.message.answer(CRISIS_REPLY)
        return

    if d.startswith("ex_"):
        k = d.replace("ex_", "")
        if k in EX:
            await c.message.answer(EX[k])
        return

    prompts = {
        "quick_тревожно": "Мне тревожно.",
        "quick_грустно": "Мне грустно.",
        "quick_злюсь": "Я злюсь.",
        "quick_сон": "Не могу уснуть.",
        "quick_отношения": "Проблемы в отношениях.",
    }
    await process(c.message, prompts.get(d, "Мне нужна поддержка."))

async def process(m: types.Message, text: str):
    cid = m.chat.id
    if is_crisis(text):
        await m.answer(CRISIS_REPLY)
        return
    add_hist(cid, "user", text)
    await bot.send_chat_action(cid, "typing")
    p = PROFILES.get(cid, {})
    sysmsg = sys_prompt(p.get("age_group", "unknown"), p.get("style", "soft"))
    if p.get("name"):
        sysmsg += f" Имя: {p['name']}."
    msgs = [{"role": "system", "content": sysmsg}] + HISTORY[cid]
    for model in MODELS:
        try:
            r = client.chat.completions.create(model=model, messages=msgs, max_tokens=600)
            ans = r.choices[0].message.content
            add_hist(cid, "assistant", ans)
            await m.answer(ans)
            return
        except Exception as e:
            print(f"[AI] {model}: {type(e).__name__}")
    await m.answer("Извини, задумался. Напиши ещё раз.\n\nЕсли плохо — 8-800-2000-122")

async def voice_txt(path: str) -> str:
    import base64
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    r = client.chat.completions.create(
        model=VOICE_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Расшифруй голосовое на русском. Только текст."},
            {"type": "input_audio", "input_audio": {"data": b64, "format": "ogg"}},
        ]}],
        max_tokens=500
    )
    return r.choices[0].message.content.strip()

@dp.message(lambda m: m.voice is not None)
async def voice(m: types.Message):
    cid = m.chat.id
    await bot.send_chat_action(cid, "typing")
    try:
        f = await bot.get_file(m.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await bot.download_file(f.file_path, tmp.name)
            p = tmp.name
        t = await voice_txt(p)
        try: os.unlink(p)
        except: pass
        if not t:
            await m.answer("Не разобрал. Напиши текстом.")
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
    if cid not in ONBOARDED and len(HISTORY[cid]) == 0:
        name = m.text.strip()[:50]
        PROFILES.setdefault(cid, {})["name"] = name
        HISTORY[cid].append({"role": "system", "content": f"Имя: {name}"})
        ONBOARDED.add(cid)
        await m.answer(f"Приятно познакомиться, {name}! 🌿\n\nСколько тебе лет?", reply_markup=kb_age())
        return
    await process(m, m.text)

async def sched():
    last = ""
    while True:
        now = datetime.now()
        cur = now.strftime("%H:%M")
        key = now.strftime("%d.%m.%Y") + "_" + cur
        if key != last:
            for cid, p in list(PROFILES.items()):
                if p.get("morning") == cur:
                    try:
                        await bot.send_message(cid, random.choice([
                            "Доброе утро 🌅 Как ты?",
                            "Утро 💙 Я рядом.",
                            "Привет 🌿 Как спалось?",
                        ]))
                    except Exception as e:
                        print(f"[MORN] {e}")
            last = key
        ts = now.timestamp()
        for cid, t, txt in [r for r in REMINDERS if r[1] <= ts]:
            try:
                await bot.send_message(cid, f"⏰ {txt}")
            except: pass
        REMINDERS[:] = [r for r in REMINDERS if r[1] > ts]
        await asyncio.sleep(30)

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
    asyncio.create_task(sched())
    print("=== SCHEDULER STARTED ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
