import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from openai import OpenAI
from aiohttp import web

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

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
    await message.answer("Привет. Я здесь, чтобы выслушать тебя. Расскажи, что тебя беспокоит?")

@dp.message()
async def chat_handler(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        response = client.chat.completions.create(
            model=model="deepseek/deepseek-chat-v3.1:free",
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            max_tokens=500
        )
        answer = response.choices[0].message.content
        await message.answer(answer)
    except Exception as e:
        print(f"Ошибка: {e}")
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
    print(f"Web server started on port {port}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
