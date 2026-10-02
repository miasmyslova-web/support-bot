import os, asyncio, random, tempfile
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
PROFILES = {}
ONBOARDED = set()

MODELS = [
    "nvidia/nemotron-3-super:free",
    "nvidia/nemotron-3-nano-omni:free",
    "dots-studio/dots-3-note-preview:free",
    "qwen/qwen-3-8-27b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "microsoft/phi-3-medium-128k-instruct:free",
    "huggingfaceh4/zephyr-7b-beta:free",
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
    base = "Ты — эмпатичный ассистент-психолог. Не ставь диагнозы. Отвечай тепло, по-человечески. Помни контекст разговора."
    age_additions = {
        "child": (
            " Пользователь — РЕБЁНОК (младше 13 лет). "
            "Говори ОЧЕНЬ простыми словами, короткими фразами. "
            "Не используй сложные термины и метафоры. "
            "Будь как добрый друг или старший брат/сестра. "
            "Обязательно спрашивай про родителей — если что-то серьёзное, советуй поговорить со взрослым, которому доверяет. "
            "Используй эмодзи, чтобы было понятнее и теплее."
        ),
        "teen": (
            " Пользователь — ПОДРОСТОК (13–17 лет). "
            "Говори простым, современным языком — как старший друг. "
            "Не используй сложные психологические термины. "
            "Не читай нотаций, не говори «в твоём возрасте», не обесценивай проблемы. "
            "У подростков сильные эмоции — будь особенно бережен. "
            "Если что-то серьёзное — мягко предложи поговорить со взрослым или позвонить на телефон доверия."
        ),
        "young": (
            " Пользователь — 18–25 лет. "
            "Говори на равных, современно, но с теплотой. "
            "Можно лёгкие метафоры и юмор. "
            "Понимай проблемы: учёба, работа, отношения, поиск себя."
        ),
        "adult": (
            " Пользователь — взрослый (26–45 лет). "
            "Говори уважительно, по-взрослому. "
            "Можно обсуждать сложные темы: работу, семью, смысл, выгорание, родительство. "
            "Не упрощай. Не сюсюкай."
        ),
        "middle": (
            " Пользователь — 46–60 лет. "
            "Говори уважительно, тепло, по-взрослому. "
            "Признавай жизненный опыт. "
            "Понимай темы: дети выросли, работа, здоровье, смысл, потери. "
            "Будь особенно терпелив."
        ),
        "older": (
            " Пользователь — старшего возраста (60+). "
            "Говори уважительно, тепло, без сюсюканья. "
            "Признавай большой жизненный опыт. "
            "Говори чуть медленнее, простыми фразами. "
            "Понимай темы: здоровье, одиночество, потери, воспоминания, внуки. "
            "Будь особенно терпелив и внимателен."
        ),
        "unknown": "",
    }
    style_additions = {
        "soft": " Общайся мягко и бережно, много поддержки.",
        "direct": " Общайся прямо и по делу, задавай конкретные вопросы.",
        "humor": " Можно легко и с юмором, но не переигрывай.",
    }
    return base + age_additions.get(age, "") + style_additions.get(style, "")

def kb_age():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧒 До 13 лет", callback_data="age_child")],
        [InlineKeyboardButton(text="🧑 13–17 лет", callback_data="age_teen")],
        [InlineKeyboardButton(text="🧑‍🎓 18–25 лет", callback_data="age_young")],
        [InlineKeyboardButton(text="🧑‍💼 26–45 лет", callback_data="age_adult")],
        [InlineKeyboardButton(text="🧓 46–60 лет", callback_data="age_middle")],
        [InlineKeyboardButton(text="👴 60+ лет", callback_data="age_older")],
        [InlineKeyboardButton(text="🤐 Пропустить", callback_data="age_skip")],
    ])

def kb_style():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤍 Мягко", callback_data="style_soft"),
         InlineKeyboardButton(text="💬 Прямо", callback_data="style_direct")],
        [InlineKeyboardButton(text="✨ С юмором", callback_data="style_humor")],
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
    "ground": "🌳 Заземление 5-4-3-2-1\n\n5 видишь, 4 слышишь, 3 коснёшься, 2 запаха, 1 вкус. Как ощущения?",
    "body": "🧘 Сканирование тела\n\nПереводи внимание: стопы → ноги → живот → грудь → руки → шея → лицо. Где напряжение — дыши туда.",
    "relax": "💪 Релаксация\n\nНапряги и расслабь: кулаки, плечи, лицо, живот, ноги. Повтори 2-3 раза.",
}

@dp.message(Command("start"))
async def start(m: types.Message):
    HISTORY[m.chat.id].clear()
    ONBOARDED.discard(m.chat.id)
    PROFILES.pop(m.chat.id, None)
    await m.answer("Привет! Я Бот поддержки 💙\n\nЯ здесь, чтобы выслушать. Как тебя зовут?")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    await m.answer(
        "Что умею:\n"
        "🎤 Голосовые\n"
        "🌬 /успокоиться\n🌳 /заземлиться\n🧘 /тело\n💪 /релакс\n"
        "👤 /profile\n🧹 /reset\n\n"
        "📞 Телефон доверия: 8-800-2000-122"
    )

@dp.message(Command("profile"))
async def profile(m: types.Message):
    p = PROFILES.get(m.chat.id, {})
    if not p:
        await m.answer("Пока ничего не знаю. /start")
        return
    ages = {
        "child": "до 13", "teen": "13–17", "young": "18–25",
        "adult": "26–45", "middle": "46–60", "older": "60+", "unknown": "—"
    }
    styles = {"soft": "мягко", "direct": "прямо", "humor": "с юмором"}
    await m.answer(
        f"👤 Имя: {p.get('name', '—')}\n"
        f"Возраст: {ages.get(p.get('age_group', 'unknown'), '—')}\n"
        f"Стиль: {styles.get(p.get('style', 'soft'), '—')}"
    )

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

    if d.startswith("age_"):
        age = d.replace("age_", "")
        if age != "skip":
            PROFILES.setdefault(cid, {})["age_group"] = age
        await c.message.answer("Отлично. Как предпочитаешь общаться?", reply_markup=kb_style())
        return

    if d.startswith("style_"):
        st = d.replace("style_", "")
        PROFILES.setdefault(cid, {})["style"] = st
        ONBOARDED.add(cid)
        await c.message.answer(
            "Спасибо! Я всё запомнил.\n\n"
            "⚠️ Я — ИИ, не живой психолог. Если плохо — 8-800-2000-122.\n\n"
            "Как ты сейчас?",
            reply_markup=kb_main()
        )
        return

    if d == "q_кризис":
        await c.message.answer(CRISIS_REPLY)
        return

    prompts = {
        "q_тревожно": "Мне тревожно.",
        "q_грустно": "Мне грустно.",
        "q_злюсь": "Я злюсь.",
        "q_сон": "Не могу уснуть.",
        "q_отношения": "Проблемы в отношениях.",
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

    random.shuffle(MODELS)
    for model in MODELS:
        try:
            r = client.chat.completions.create(model=model, messages=msgs, max_tokens=600)
            ans = r.choices[0].message.content
            add_hist(cid, "assistant", ans)
            await m.answer(ans)
            print(f"[OK] {model}")
            return
        except Exception as e:
            print(f"[AI] {model}: {type(e).__name__}")

    await m.answer(
        "Извини, все модели сейчас перегружены. Попробуй через минуту.\n\n"
        "Если плохо — 8-800-2000-122"
    )

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
    
    # ЖДЁМ, ЧТОБЫ СТАРЫЙ КОНТЕЙНЕР УМЕР
    print("=== ЖДУ 15 СЕКУНД, ЧТОБЫ СТАРЫЙ КОНТЕЙНЕР УМЕР ===")
    await asyncio.sleep(15)
    
    # Удаляем вебхук, чтобы точно не было конфликтов
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("=== ВЕБХУК УДАЛЁН ===")
    except Exception as e:
        print(f"[WEBHOOK] {e}")
    
    print("=== НАЧИНАЮ СЛУШАТЬ TELEGRAM ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
