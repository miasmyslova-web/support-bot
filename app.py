import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
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

# Список бесплатных моделей — пробуем по очереди
FREE_MODELS = [
    "nvidia/nemotron-3-super:free",
    "qwen/qwen-3-8-27b:free",
    "google/gemma-4-31b-it:free",
    "dots-studio/dots-3-note-preview:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

SYSTEM_PROMPT = """Ты — эмпатичный и поддерживающий ассистент-психолог. 
Твоя задача — слушать пользователя, задавать уточняющие вопросы и помогать ему разобраться в чувствах. 
Не ставь диагнозы и не давай медицинских советов. 
Отвечай тепло, по-человечески, без шаблонных фраз."""

# ===== КРИЗИСНАЯ ЗАЩИТА =====
# Расширенный список кризисных слов и фраз
CRISIS_WORDS = [
    # Прямые упоминания смерти и суицида
    "умираю", "умереть", "умру", "смерть", "мёртв", "мертв",
    "суицид", "самоубий", "покончить с собой", "покончить жизнь",
    "убить себя", "убью себя", "не хочу жить", "не хочу больше жить",
    "хочу умереть", "хочу сдохнуть", "нет смысла жить", "жизнь не имеет смысла",
    # Самоповреждение
    "резать себя", "порезы", "порезал", "порезала", "вскрыть вены",
    "вскрыл вены", "вскрыла вены", "режу вены",
    # Способы
    "повеситься", "повешусь", "спрыгнуть с крыши", "спрыгнуть с моста",
    "наглотаться таблеток", "выпить таблетки", "передозировка",
    # Общие тревожные
    "прощай", "прощайте", "я больше не могу", "нет выхода",
    "всё кончено", "все кончено", "это конец"
]

CRISIS_REPLY = """Я слышу тебя. То, что ты сейчас чувствуешь — это очень тяжело, и я хочу, чтобы ты знал: ты не один.

Пожалуйста, прямо сейчас позвони туда, где тебе помогут живые люди:

📞 **8-800-2000-122** — бесплатный телефон доверия для детей, подростков и их родителей (круглосуточно, анонимно, по всей России)
📞 **8-495-989-50-50** — круглосуточная психологическая помощь (Москва, но принимают звонки со всей страны)
📞 **8-800-333-44-34** — Всероссийская линия помощи
📞 **112** — единый номер экстренных служб (если опасность прямо сейчас)

Также можно написать в чат психологической помощи:
💬 **МЧС России: чат-бот @MCHS_Russia_bot**
💬 **Телефон доверия для детей и подростков**

Ты важен. Пожалуйста, не оставайся с этим один. Позвони — там ответят люди, которые умеют помогать в таких ситуациях.

Я остаюсь здесь, если ты захочешь просто поговорить."""

def is_crisis(text: str) -> bool:
    """Проверяет, есть ли в сообщении кризисные слова."""
    low = text.lower()
    return any(word in low for word in CRISIS_WORDS)

# ===== ОСНОВНЫЕ ОБРАБОТЧИКИ =====

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    print(f"[START] {message.chat.id}")
    await message.answer(
        "Привет. Я здесь, чтобы выслушать тебя. Расскажи, что тебя беспокоит?\n\n"
        "⚠️ Я — ИИ-ассистент, а не живой психолог. Если тебе нужна срочная помощь, "
        "позвони на телефон доверия: 8-800-2000-122."
    )

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(
        "Просто напиши мне, что тебя беспокоит — я постараюсь помочь.\n\n"
        "📞 Телефон доверия: 8-800-2000-122 (круглосуточно, бесплатно, анонимно)\n"
        "📞 Экстренные службы: 112\n\n"
        "⚠️ Я не заменяю живого специалиста."
    )

@dp.message()
async def chat_handler(message: types.Message):
    print(f"[MSG] {message.text[:50]}")
    
    # Проверка на кризисное состояние
    if is_crisis(message.text):
        print(f"[CRISIS] обнаружено кризисное сообщение")
        await message.answer(CRISIS_REPLY)
        return
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    last_error = None
    for model_name in FREE_MODELS:
        try:
            print(f"[AI] пробую модель: {model_name}")
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message.text}
                ],
                max_tokens=500
            )
            answer = response.choices[0].message.content
            await message.answer(answer)
            print(f"[BOT] ответ отправлен (модель: {model_name})")
            return
        except Exception as e:
            print(f"[AI] модель {model_name} не сработала: {type(e).__name__}")
            last_error = e
            continue
    
    print(f"[ERROR] все модели недоступны: {last_error}")
    await message.answer(
        "Извини, я немного задумался. Попробуй написать еще раз.\n\n"
        "Если тебе плохо прямо сейчас — позвони: 8-800-2000-122"
    )

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
    print(f"=== ВЕБ-СЕРВЕР ЗАПУЩЕН НА ПОРТУ {port} ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
    
