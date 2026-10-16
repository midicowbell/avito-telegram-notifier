import asyncio
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import httpx
import uvicorn

# ================= КОНФИГУРАЦИЯ =================
load_dotenv()
AVITO_CLIENT_ID = os.getenv("AVITO_CLIENT_ID")
AVITO_CLIENT_SECRET = os.getenv("AVITO_CLIENT_SECRET")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not all(
    [AVITO_CLIENT_ID, AVITO_CLIENT_SECRET, TG_BOT_TOKEN, TG_CHAT_ID, WEBHOOK_URL]
):
    raise ValueError(
        "❌ Ошибка: Проверьте файл .env, одна или несколько переменных не заполнены!"
    )
# ================================================

AVITO_TOKEN_URL = "https://api.avito.ru/token/"
AVITO_WEBHOOK_URL = "https://api.avito.ru/messenger/v3/webhook"
AVITO_SELF_URL = "https://api.avito.ru/core/v1/accounts/self"
TG_API_URL = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"

my_avito_user_id = None
avito_access_token = None


async def get_avito_token():
    """Получение и обновление токена доступа Авито"""
    global avito_access_token
    async with httpx.AsyncClient() as client:
        data = {
            "grant_type": "client_credentials",
            "client_id": AVITO_CLIENT_ID,
            "client_secret": AVITO_CLIENT_SECRET,
        }
        res = await client.post(AVITO_TOKEN_URL, data=data)
        res_data = res.json()
        avito_access_token = res_data.get("access_token")
        return avito_access_token


async def get_my_account_id():
    """Получение своего ID на Авито (чтобы отличать свои сообщения от сообщений клиентов)"""
    global my_avito_user_id
    headers = {"Authorization": f"Bearer {avito_access_token}"}
    async with httpx.AsyncClient() as client:
        res = await client.get(AVITO_SELF_URL, headers=headers)
        data = res.json()
        my_avito_user_id = data.get("id")
        return my_avito_user_id


async def register_avito_webhook():
    """Регистрация вебхука в Авито"""
    headers = {
        "Authorization": f"Bearer {avito_access_token}",
        "Content-Type": "application/json",
    }
    payload = {"url": WEBHOOK_URL}
    async with httpx.AsyncClient() as client:
        res = await client.post(AVITO_WEBHOOK_URL, json=payload, headers=headers)
        return res.json()


async def send_tg_notification(text: str, chat_id_avito: str):
    """Отправка уведомления в Telegram"""
    # Ссылка для мгновенного перехода в чат на Авито
    avito_chat_link = f"https://www.avito.ru/profile/messenger/channel/{chat_id_avito}"

    message = (
        f"🔔 <b>Новое сообщение на Авито!</b>\n\n"
        f"💬 <b>Текст:</b> {text}\n\n"
        f"👉 <a href='{avito_chat_link}'>Открыть диалог на Авито</a>"
    )

    data = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_notification": False,  # Громкий звук уведомления!
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(TG_API_URL, json=data)
        except Exception as e:
            print(f"Ошибка отправки в Telegram: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Действия при запуске скрипта
    print("🚀 Авторизация в Авито...")
    token = await get_avito_token()
    if not token:
        print("❌ Ошибка авторизации в Авито! Проверьте Client ID и Secret.")
        return

    user_id = await get_my_account_id()
    print(f"✅ Успешно! Ваш Avito User ID: {user_id}")

    print(f"🔗 Привязка Webhook на {WEBHOOK_URL}...")
    reg_status = await register_avito_webhook()
    print(f"✅ Статус привязки Webhook: {reg_status}")
    print("🟢 Бот готов и ожидает сообщений!")
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def handle_avito_webhook(request: Request):
    """Сюда Авито отправляет вебхуки о новых сообщениях"""
    try:
        data = await request.json()
        print("\n" + "=" * 40)
        print("📥 ПРИШЕЛ ВЕБХУК ОТ АВИТО!")
        print(f"Данные: {data}")
        print("=" * 40 + "\n")

        payload = data.get("payload", {}).get("value", {})

        author_id = payload.get("author_id")
        chat_id = payload.get("chat_id")
        content = payload.get("content", {})
        msg_text = content.get("text", "[Вложение / Системное сообщение]")

        # Проверка, кто автор
        if author_id == my_avito_user_id:
            print(
                f"ℹ️ Сообщение от самого себя (ID: {author_id}), пропускаем."
            )
            return {"status": "ok"}

        print(
            f"🚀 Отправляем в Telegram от клиента {author_id}: '{msg_text}'..."
        )
        await send_tg_notification(msg_text, chat_id)
        print("✅ Успешно отправлено в Telegram!")

    except Exception as e:
        print(f"❌ Ошибка обработки вебхука: {e}")

    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)