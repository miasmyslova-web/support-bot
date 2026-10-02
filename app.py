import os
from openai import OpenAI
from aiohttp import web

print("=== ТЕСТ ===")

GROQ_KEY = os.getenv("GROQ_API_KEY")
print(f"GROQ key loaded: {'yes' if GROQ_KEY else 'NO'}")
print(f"Key starts with: {GROQ_KEY[:8] if GROQ_KEY else 'none'}")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY,
)

async def handle(req):
    # Пробуем подключиться к Groq
    try:
        r = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "Say hello in Russian"}],
            max_tokens=50
        )
        result = r.choices[0].message.content
        print(f"[GROQ OK] {result}")
        return web.Response(text=f"GROQ OK: {result}")
    except Exception as e:
        print(f"[GROQ ERROR] {type(e).__name__}: {e}")
        return web.Response(text=f"GROQ ERROR: {type(e).__name__}: {e}")

async def main():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    print(f"=== WEB SERVER ON PORT {port} ===")
    # Просто тестируем Groq один раз при старте
    await handle(None)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
