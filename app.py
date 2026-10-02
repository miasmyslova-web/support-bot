import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI
from aiohttp import web

print("=== БОТ ЗАПУСКАЕТСЯ ===")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

print(f"Токен Telegram загружен: {'да' if TELEGRAM_TOKEN else 'НЕТ'}")
print(f"Ключ OpenRouter загружен: {'да' if OPENROUTER_KEY else 'НЕТ'}")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

SYSTEM_PROMPT = """Ты — эмпатичный и поддерживающий ассистент-психолог. 
Твоя задача — слушать пользователя, задавать уточняющие вопросы и помогать ему разобраться в чувствах. 
Не ставь диагнозы и не давай медицинских советов. 
Если пользователь говорит о суициде или самоповреждении, вежливо предложи обратиться к специалисту или на телефон доверия."""

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    print(f"[START] получена команда от {message.chat.id}")
    await message.answer("Привет. Я здесь, чтобы выслушать тебя. Расскажи, что тебя беспокоит?")

@dp.message()
async def chat_handler(message: types.Message):
    print(f"[MSG] получено сообщение: {message.text[:50]}")
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        print(f"[AI] отправляю запрос в OpenRouter...")
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-super:free",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            max_tokens=500
        )
        print(f"[AI] получен ответ от OpenRouter")
        answer = response.choices[0].message.content
        await message.answer(answer)
        print(f"[BOT] ответ отправлен пользователю")
    except Exception as e:
        print(f"[ERROR] ОШИБКА: {type(e).__name__}: {e}")
        await message.answer("Извини, я немного задумался. Попробуй написать еще раз.")

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
    
    print("=== НАЧИНАЮ СЛУШАТЬ TELEGRAM ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
