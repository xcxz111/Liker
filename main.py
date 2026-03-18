import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from db.database import create_pool
from db.tables import create_tables
from connecting import connect_all_clients
from handlers_accounts import router as accounts_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Telethon часто пишет INFO-шум (updates/diff для channel/user).
# Снижаем уровень логов Telethon, чтобы не утонуть в консоли.
for telethon_logger_name in (
    "telethon",
    "telethon.client",
    "telethon.client.updates",
    "telethon.client.users",
):
    logging.getLogger(telethon_logger_name).setLevel(logging.WARNING)


def load_config() -> dict:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Не найден BOT_TOKEN в окружении. "
            "Создайте файл .env (см. .env.example) и укажите BOT_TOKEN."
        )

    admin_id_raw = os.getenv("ADMIN_ID")
    admin_id = int(admin_id_raw) if admin_id_raw else None

    if not admin_id:
        raise RuntimeError(
            "Не найден ADMIN_ID в окружении. "
            "Добавьте свой Telegram ID в .env."
        )

    country_folder = os.getenv("COUNTRY_FOLDER", "accounts")

    return {
        "bot_token": token,
        "admin_id": admin_id,
        "country_folder": country_folder,
    }


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logger.info("Бот запущен как @%s (id=%s)", me.username, me.id)


async def main() -> None:
    config = load_config()

    # Бот
    bot = Bot(
        token=config["bot_token"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Ограничиваем все сообщения и колбэки только админом
    admin_id = config["admin_id"]
    dp.message.filter(F.from_user.id == admin_id)
    dp.callback_query.filter(F.from_user.id == admin_id)

    # База данных
    pool = await create_pool()
    await create_tables(pool)
    dp["db"] = pool

    # При каждом запуске сбрасываем статус всех аккаунтов в 'off'
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE users SET user_status = 'off'")

    # Глобальный lock для работы с файлом ссылок
    file_lock = asyncio.Lock()
    dp["file_lock"] = file_lock

    # Подключаем аккаунты Telethon и пишем их в таблицу users
    clients = await connect_all_clients(config["country_folder"], pool)
    dp["clients"] = clients
    dp["client_tasks"] = {}

    # Подключаем роутер с командами и колбэками
    dp.include_router(accounts_router)

    # Регистрация служебных хендлеров
    dp.startup.register(on_startup)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")

