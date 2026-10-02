import os, asyncio, random, tempfile, re
from datetime import datetime
from collections import defaultdict
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from openai import OpenAI
from aiohttp import web

print("=== START ===")

TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")

print(f"GROQ key loaded: {'yes' if GROQ_KEY else 'NO'}")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY,
)

bot = Bot(token=TOKEN)
dp = Dispatcher()

HISTORY = defaultdict(list)
PROFILES = {}
ONBOARDED = set()

# ===== ПАМЯТЬ =====
MAX_HISTORY = 40  # было 20 — увеличили

MODELS = []

def load_models():
    try:
        response = client.models.list()
        all_models = [m.id for m in response.data]
        chat_models = []
        for m in all_models:
            if any(x in m for x in ["whisper", "tts", "embedding", "guard"]):
                continue
            chat_models.append(m)
        if not chat_models:
            chat_models = ["openai/gpt-oss-20b"]
        print(f"[MODELS] Доступно: {chat_models}")
        return chat_models
    except Exception as e:
        print(f"[MODELS ERROR] {type(e).__name__}: {e}")
        return ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

VOICE_MODEL = "whisper-large-v3"

# ===== РАЗНЫЕ ВАРИАНТЫ =====
GREETINGS = [
    "Привет. Я ИИ-помощник. Тут можно говорить обо всём, без осуждения. Как тебя зовут?",
    "Здравствуй. Я здесь, чтобы выслушать. Как тебя зовут?",
    "Привет. Я рядом. Расскажи, как тебя зовут?",
    "Привет. Я ИИ-помощник, устрою тебе уютное место для разговора. Как тебя зовут?",
    "Здравствуй. Тут тебя никто не осудит. Как тебя зовут?",
]

FAREWELLS = [
    "Спасибо, что поговорил со мной. Береги себя.",
    "Я рядом, если снова понадоблюсь. Хорошего дня.",
    "Спасибо за доверие. Заглядывай, когда захочется поговорить.",
    "Береги себя. Ты важен.",
    "Было тепло с тобой поговорить. До встречи.",
    "Отдыхай. Если что — я тут.",
]

ERROR_REPLIES = [
    "Ой, я немного задумался. Повтори, пожалуйста.",
    "Прости, что-то я завис. Напиши ещё раз.",
    "Извини, я отвлёкся. Что ты хотел сказать?",
    "Ох, задумался. Повтори, пожалуйста.",
    "Прости, я тут немного потерялся. Напиши снова.",
    "Что-то я замер. Давай ещё раз?",
]

AFTER_ONBOARD = [
    "Спасибо. Я всё запомнил.\n\nВажно: я ИИ, а не живой психолог. Если будет плохо — 8-800-2000-122.\n\nРасскажи, что у тебя на душе?",
    "Хорошо, я запомнил.\n\nЯ — ИИ, не живой специалист. Если станет совсем тяжело — 8-800-2000-122.\n\nО чём хочешь поговорить?",
    "Спасибо. Всё запомнил.\n\nНапомню: я не заменяю живого психолога. Если плохо — 8-800-2000-122.\n\nКак ты сейчас?",
    "Запомнил. Спасибо.\n\nЯ ИИ, если что-то серьёзное — 8-800-2000-122.\n\nРасскажи, что тебя беспокоит?",
    "Готово. Я всё сохранил.\n\nЯ ИИ-помощник, не заменяю специалиста. Если тяжело — 8-800-2000-122.\n\nС чего начнём?",
]

CRISIS_WORDS = [
    "умираю", "умереть", "умру", "смерть", "суицид", "самоубий",
    "не хочу жить", "хочу умереть", "убить себя", "покончить",
    "резать", "порезы", "повеситься", "передозировка",
    "прощай", "нет выхода", "всё кончено", "хочу исчезнуть",
]

CRISIS_REPLY = """Я слышу тебя. То, что ты сейчас чувствуешь — очень тяжело, и ты не один.

Пожалуйста, позвони туда, где помогут живые люди:
8-800-2000-122 — телефон доверия (круглосуточно, анонимно)
8-495-989-50-50 — психологическая помощь
8-800-333-44-34 — Всероссийская линия
112 — экстренные службы

Ты важен. Не оставайся с этим один."""

def is_crisis(t):
    t = t.lower()
    return any(w in t for w in CRISIS_WORDS)

def add_hist(cid, role, content):
    HISTORY[cid].append({"role": role, "content": content})
    if len(HISTORY[cid]) > MAX_HISTORY:
        HISTORY[cid] = HISTORY[cid][-MAX_HISTORY:]

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

def sys_prompt(age=None, style="soft"):
    base = (
        "Ты — тёплый, живой ИИ-помощник. Не называй себя именем, просто ИИ-помощник. "
        "Говори как человек, а не как учебник. Коротко, естественно, с эмпатией. "
        "Не ставь диагнозы, не давай медицинских советов. "
        "Ты — собеседник, а не справочник. "
        "Твоя задача — создавать уют. Человек должен чувствовать себя в безопасности, "
        "как будто он пришёл в тихое тёплое место, где его выслушают без осуждения. "
        "Не пиши «я [имя]», не представляйся именем пользователя. Ты — просто ИИ-помощник. "
        "Не используй много эмодзи — максимум один-два на сообщение. "
        "Не пиши списки и нумерации без необходимости. "
        "Не начинай каждый ответ с шаблонов типа «Я слышу тебя» или «Это тяжело». "
        "Задавай мягкие открытые вопросы, но не допрашивай. "
        "Помни контекст разговора."
    )
    if age is None:
        age_add = ""
    else:
        group = get_age_group(age)
        age_additions = {
            "child": (
                f" Пользователю {age} лет — это ребёнок. "
                "Говори простыми словами, короткими фразами, тепло, как добрый старший друг. "
                "Без сложных терминов. Если серьёзное — советуй поговорить с родителями."
            ),
            "teen": (
                f" Пользователю {age} лет — подросток. "
                "Говори простым, современным языком, как старший друг. "
                "Без нравоучений. Не обесценивай проблемы."
            ),
            "young": (
                f" Пользователю {age} лет — 18-25. "
                "На равных, современно, тепло."
            ),
            "adult": (
                f" Пользователю {age} лет — взрослый. "
                "Уважительно, по-взрослому."
            ),
            "middle": (
                f" Пользователю {age} лет. "
                "Уважительно, тепло. Признавай жизненный опыт."
            ),
            "older": (
                f" Пользователю {age} лет — старший возраст. "
                "Уважительно, тепло, чуть медленнее."
            ),
        }
        age_add = age_additions.get(group, "")
    style_additions = {
        "soft": " Общайся мягко и бережно.",
        "direct": " Общайся прямо и по делу.",
        "humor": " Можно легко, с лёгким юмором.",
    }
    return base + age_add + style_additions.get(style, "")

def kb_style():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Мягко", callback_data="style_soft"),
         InlineKeyboardButton(text="Прямо", callback_data="style_direct")],
        [InlineKeyboardButton(text="С юмором", callback_data="style_humor")],
    ])

EX = {
    "breath": "Дыхание 4-4-4\n\nВдох 4 сек, задержка 4, выдох 4. Повтори 5 раз. Как ты?",
    "ground": "Заземление 5-4-3-2-1\n\n5 видишь, 4 слышишь, 3 коснёшься, 2 запаха, 1 вкус. Как ощущения?",
    "body": "Сканирование тела\n\nПереводи внимание: стопы, ноги, живот, грудь, руки, шея, лицо. Где напряжение — дыши туда.",
    "relax": "Релаксация\n\nНапряги и расслабь: кулаки, плечи, лицо, живот, ноги. Повтори 2-3 раза.",
}

@dp.message(Command("start"))
async def start(m: types.Message):
    HISTORY[m.chat.id].clear()
    ONBOARDED.discard(m.chat.id)
    PROFILES.pop(m.chat.id, None)
    await m.answer(random.choice(GREETINGS))

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    await m.answer(
        "Что я умею:\n\n"
        "Если очень плохо — напиши мне, дам телефон доверия.\n\n"
        "Упражнения:\n"
        "/успокоиться — дыхание\n"
        "/заземлиться — техника 5-4-3-2-1\n"
        "/тело — сканирование тела\n"
        "/релакс — прогрессивная релаксация\n\n"
        "Можно отправлять голосовые.\n\n"
        "/profile — что я о тебе знаю\n"
        "/reset — начать заново\n"
        "/stop — попрощаться\n\n"
        "Телефон доверия: 8-800-2000-122\n"
        "Я не заменяю живого специалиста."
    )

@dp.message(Command("profile"))
async def profile(m: types.Message):
    p = PROFILES.get(m.chat.id, {})
    if not p:
        await m.answer("Пока ничего не знаю. /start")
        return
    styles = {"soft": "мягко", "direct": "прямо", "humor": "с юмором"}
    age = p.get("age", "—")
    group_names = {"child": "ребёнок", "teen": "подросток", "young": "молодой",
                   "adult": "взрослый", "middle": "средний", "older": "старший"}
    group = f" ({group_names.get(get_age_group(age), '')})" if age != "—" else ""
    await m.answer(
        f"Имя: {p.get('name', '—')}\n"
        f"Возраст: {age}{group}\n"
        f"Стиль: {styles.get(p.get('style', 'soft'), '—')}"
    )

@dp.message(Command("reset"))
async def reset(m: types.Message):
    HISTORY[m.chat.id].clear()
    await m.answer(random.choice([
        "Начнём заново. О чём поговорим?",
        "Хорошо, с чистого листа. Что тебя беспокоит?",
        "Начнём сначала. Расскажи, что на душе.",
    ]))

@dp.message(Command("stop"))
async def stop_cmd(m: types.Message):
    await m.answer(random.choice(FAREWELLS))

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
        ONBOARDED.add(cid)
        await c.message.answer(random.choice(AFTER_ONBOARD))
        return

    prompts = {
        "q_тревожно": "Мне тревожно.", "q_грустно": "Мне грустно.",
        "q_злюсь": "Я злюсь.", "q_сон": "Не могу уснуть.",
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
    sysmsg = sys_prompt(p.get("age"), p.get("style", "soft"))
    if p.get("name"):
        sysmsg += f" Имя пользователя: {p['name']}. Это его имя, не твоё. Ты — ИИ-помощник без имени."
    msgs = [{"role": "system", "content": sysmsg}] + HISTORY[cid]

    for model in MODELS:
        try:
            r = client.chat.completions.create(model=model, messages=msgs, max_tokens=500)
            ans = r.choices[0].message.content
            add_hist(cid, "assistant", ans)
            await m.answer(ans)
            print(f"[OK] {model}")
            return
        except Exception as e:
            print(f"[AI] {model}: {type(e).__name__}: {e}")

    await m.answer(random.choice(ERROR_REPLIES))

async def voice_txt(path: str) -> str:
    with open(path, "rb") as f:
        r = client.audio.transcriptions.create(
            model=VOICE_MODEL,
            file=f,
        )
    return r.text.strip()

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
        await m.answer(f"Я услышал: {t}")
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
        HISTORY[cid].append({"role": "system", "content": f"Имя пользователя: {name}. Это его имя, не твоё. Ты — ИИ-помощник без имени."})
        ONBOARDED.add(cid)
        await m.answer(f"Приятно познакомиться, {name}. Сколько тебе лет? Напиши цифрой.")
        return

    if "age" not in p:
        age = parse_age(m.text)
        if age is None:
            await m.answer("Не понял. Напиши просто цифрой: 15, 25, 40, 65.")
            return
        p["age"] = age
        group = get_age_group(age)
        replies = {
            "child": "Понял. Буду говорить просто.",
            "teen": "Понял. Буду общаться по-дружески.",
            "young": "Понял.",
            "adult": "Понял.",
            "middle": "Понял.",
            "older": "Понял. Буду говорить уважительно, не спеша.",
        }
        await m.answer(f"{replies.get(group, 'Спасибо.')}\n\nКак предпочитаешь общаться?", reply_markup=kb_style())
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

    global MODELS
    MODELS = load_models()
    print(f"=== ЗАГРУЖЕНО {len(MODELS)} МОДЕЛЕЙ ===")

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
