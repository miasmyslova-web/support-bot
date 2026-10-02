import os, asyncio, random, tempfile, re
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

# ===== ПАРСИНГ ВОЗРАСТА =====
def parse_age(text: str):
    """Пытается извлечь возраст из текста."""
    text = text.strip().lower()
    
    # Ищем число
    numbers = re.findall(r'\d+', text)
    if not numbers:
        # Может, написали словом?
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

# ===== ОПРЕДЕЛЕНИЕ ВОЗРАСТНОЙ ГРУППЫ =====
def get_age_group(age: int) -> str:
    if age < 13:
        return "child"
    elif age < 18:
        return "teen"
    elif age < 26:
        return "young"
    elif age < 46:
        return "adult"
    elif age < 61:
        return "middle"
    else:
        return "older"

# ===== ПРОМПТ ПО ВОЗРАСТУ =====
def sys_prompt(age=None, style="soft"):
    base = "Ты — эмпатичный ассистент-психолог. Не ставь диагнозы. Отвечай тепло, по-человечески. Помни контекст разговора."
    
    if age is None:
        age_add = ""
    else:
        group = get_age_group(age)
        
        age_additions = {
            "child": (
                f" Пользователю {age} лет — это РЕБЁНОК. "
                "Говори ОЧЕНЬ простыми словами, короткими фразами, будто объясняешь младшему. "
                "Никаких сложных терминов, метафор, абстракций. "
                "Будь как добрый старший друг или старший брат/сестра. "
                "Используй много эмодзи, чтобы было тепло и понятно. "
                "Обязательно спрашивай про родителей — если что-то серьёзное, советуй поговорить со взрослым, которому ребёнок доверяет."
            ),
            "teen": (
                f" Пользователю {age} лет — это ПОДРОСТОК. "
                "Говори простым, современным языком — как старший друг, не как учитель. "
                "Никаких сложных психологических терминов. "
                "Не читай нотаций, не говори «в твоём возрасте», не обесценивай проблемы. "
                "У подростков сильные эмоции, гормоны, всё воспринимается острее — будь особенно бережен. "
                "Если что-то серьёзное — мягко предложи поговорить со взрослым, которому доверяет, или позвонить на телефон доверия."
            ),
            "young": (
                f" Пользователю {age} лет — это молодой человек. "
                "Говори на равных, современно, но с теплотой. "
                "Можно лёгкие метафоры и юмор, но не переигрывай. "
                "Понимай проблемы: учёба, работа, отношения, поиск себя, переезды, самооценка, тревога о будущем."
            ),
            "adult": (
                f" Пользователю {age} лет — это взрослый человек. "
                "Говори уважительно, по-взрослому, на равных. "
                "Можно обсуждать сложные темы: работу, семью, смысл, выгорание, родительство, отношения, потери. "
                "Не упрощай. Не сюсюкай. Не давай банальных советов."
            ),
            "middle": (
                f" Пользователю {age} лет. "
                "Говори уважительно, тепло, по-взрослому. "
                "Признавай жизненный опыт. "
                "Понимай темы: дети выросли, работа, здоровье, смысл, потери, отношения, изменения в теле. "
                "Будь особенно терпелив."
            ),
            "older": (
                f" Пользователю {age} лет — это человек старшего возраста. "
                "Говори уважительно, тепло, без сюсюканья и снисходительности. "
                "Признавай большой жизненный опыт. "
                "Говори чуть медленнее, простыми, но не примитивными фразами. "
                "Понимай темы: здоровье, одиночество, потери, воспоминания, дети и внуки, страх. "
                "Будь особенно терпелив и внимателен, не торопи."
            ),
        }
        age_add = age_additions.get(group, "")
    
    style_additions = {
        "soft": " Общайся мягко и бережно, много поддержки.",
        "direct": " Общайся прямо и по делу, задавай конкретные вопросы.",
        "humor": " Можно легко и с юмором, но не переигрывай.",
    }
    return base + age_add + style_additions.get(style, "")

# ===== КНОПКИ =====

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
        "🆘 Если очень плохо\n"
        "Напиши мне — я дам телефон доверия.\n\n"
        "🌬 Упражнения от тревоги\n"
        "/успокоиться — дыхание 4-4-4\n"
        "/заземлиться — техника 5-4-3-2-1\n"
        "/тело — сканирование тела\n"
        "/релакс — прогрессивная релаксация\n\n"
        "🎤 Голосовые\n"
        "Можешь отправить голосовое — я расшифрую и отвечу.\n\n"
        "👤 /profile — что я о тебе знаю\n"
        "🧹 /reset — начать разговор заново\n\n"
        "📞 Телефон доверия: 8-800-2000-122\n"
        "📞 Экстренные службы: 112\n\n"
        "⚠️ Я не заменяю живого специалиста."
    )

@dp.message(Command("profile"))
async def profile(m: types.Message):
    p = PROFILES.get(m.chat.id, {})
    if not p:
        await m.answer("Пока ничего не знаю. /start")
        return
    styles = {"soft": "мягко", "direct": "прямо", "humor": "с юмором"}
    age = p.get("age", "—")
    group_names = {
        "child": "ребёнок", "teen": "подросток", "young": "молодой",
        "adult": "взрослый", "middle": "средний возраст", "older": "старший возраст"
    }
    group = ""
    if age != "—":
        group = f" ({group_names.get(get_age_group(age), '')})"
    await m.answer(
        f"👤 Имя: {p.get('name', '—')}\n"
        f"Возраст: {age}{group}\n"
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

# ===== CALLBACK =====

@dp.callback_query()
async def cb(c: CallbackQuery):
    d = c.data
    cid = c.message.chat.id
    await c.answer()

    if d.startswith("style_"):
        st = d.replace("style_", "")
        PROFILES.setdefault(cid, {})["style"] = st
        ONBOARDED.add(cid)
        await c.message.answer(
            "Спасибо! Я всё запомнил 🌿\n\n"
            "💡 Что я умею:\n"
            "• Просто поговорить и поддержать\n"
            "• 🌬 /успокоиться — дыхание при тревоге\n"
            "• 🌳 /заземлиться — техника 5-4-3-2-1\n"
            "• 🧘 /тело — сканирование тела\n"
            "• 💪 /релакс — прогрессивная релаксация\n"
            "• 🎤 Можно отправлять голосовые\n"
            "• 👤 /profile — что я о тебе знаю\n\n"
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

# ===== ОСНОВНАЯ ЛОГИКА =====

async def process(m: types.Message, text: str):
    cid = m.chat.id
    if is_crisis(text):
        await m.answer(CRISIS_REPLY)
        return
    add_hist(cid, "user", text)
    await bot.send_chat_action(cid, "typing")
    p = PROFILES.get(cid, {})
    sysmsg = sys_prompt(p.get("age"), p.get("style", "soft"))
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

# ===== ГОЛОСОВЫЕ =====

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
    p = PROFILES.setdefault(cid, {})

    # Шаг 1: имя
    if cid not in ONBOARDED and len(HISTORY[cid]) == 0:
        name = m.text.strip()[:50]
        p["name"] = name
        HISTORY[cid].append({"role": "system", "content": f"Имя: {name}"})
        ONBOARDED.add(cid)
        await m.answer(
            f"Приятно познакомиться, {name}! 🌿\n\n"
            "Сколько тебе лет? Напиши цифрой (например: 17 или 42).\n\n"
            "Это поможет мне общаться с тобой комфортнее — под твой возраст."
        )
        return

    # Шаг 2: возраст
    if cid not in ONBOARDED or "age" not in p:
        age = parse_age(m.text)
        if age is None:
            await m.answer(
                "Не понял возраст 🤔\n"
                "Напиши просто цифрой, например: 15, 25, 40, 65."
            )
            return
        p["age"] = age
        # Определяем группу для приятного ответа
        group = get_age_group(age)
        group_replies = {
            "child": "Понял! Буду говорить с тобой просто и понятно 🌟",
            "teen": "Понял! Буду общаться с тобой по-дружески 🌿",
            "young": "Понял! Будем общаться на равных 💬",
            "adult": "Понял, спасибо 🌿",
            "middle": "Понял, спасибо 🌿",
            "older": "Понял, спасибо. Буду говорить уважительно и не спеша 🌿",
        }
        await m.answer(
            f"{group_replies.get(group, 'Спасибо!')}\n\n"
            f"Как ты предпочитаешь общаться?",
            reply_markup=kb_style()
        )
        return

    print(f"[MSG] {m.text[:50]}")
    await process(m, m.text)

# ===== ВЕБ-СЕРВЕР =====

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
    
    print("=== ЖДУ 15 СЕКУНД, ЧТОБЫ СТАРЫЙ КОНТЕЙНЕР УМЕР ===")
    await asyncio.sleep(15)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("=== ВЕБХУК УДАЛЁН ===")
    except Exception as e:
        print(f"[WEBHOOK] {e}")
    
    print("=== НАЧИНАЮ СЛУШАТЬ TELEGRAM ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
