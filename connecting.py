import glob
import logging
import os
import asyncio
import random

from telethon import TelegramClient, events
from dotenv import load_dotenv


load_dotenv()

API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = os.getenv("API_HASH", "")

logger = logging.getLogger(__name__)


def load_sessions(base_path: str) -> list[str]:
    """
    Ищем все файлы, оканчивающиеся на .session, рекурсивно внутри base_path.
    Например: accounts/DE/1234567890/session.dat.session
    """
    pattern = os.path.join(base_path, "**", "*.session")
    session_files = glob.glob(pattern, recursive=True)

    # Telethon обычно использует путь без расширения .session как имя сессии
    sessions = [s[:-8] if s.endswith(".session") else s for s in session_files]
    logger.info("Найдено сессий: %s", len(sessions))
    return sessions


def attach_private_message_handler(client: TelegramClient, pool):
    """
    Подключаем обработчик входящих личных сообщений:
    - только приватные диалоги
    - не от самого аккаунта
    - не от ботов
    Отвечаем текстом из users.user_message, если он задан.
    """

    @client.on(events.NewMessage(incoming=True))
    async def _handler(event):  # noqa: D401
        # Только приватные диалоги, не каналы/группы
        if not event.is_private or event.is_channel:
            return
        # Пропускаем исходящие (от самого аккаунта)
        if event.out:
            return

        try:
            sender = await event.get_sender()
            if getattr(sender, "bot", False):
                return
        except Exception:
            return

        # Берём сообщение для этого аккаунта из БД
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT user_message FROM users WHERE user_id = %s",
                        (client._self_id,),
                    )
                    row = await cur.fetchone()
        except Exception as exc:
            logger.warning("❌ Ошибка при получении user_message: %s", exc)
            return

        if not row:
            return

        user_message = row[0]
        if not user_message:
            return

        # Инициализируем множество уже обработанных отправителей для этого клиента
        if not hasattr(client, "_auto_replied_users"):
            client._auto_replied_users = set()

        sender_id = event.sender_id
        if sender_id in client._auto_replied_users:
            return

        # Ставим задержку перед ответом
        await asyncio.sleep(random.randint(15, 25))

        try:
            await event.respond(user_message)
            client._auto_replied_users.add(sender_id)
            logger.info("✉️ Автоответ отправлен из %s в личку", client._self_id)
        except Exception as exc:
            logger.warning("❌ Не удалось отправить автоответ: %s", exc)


async def connect_all_clients(account_path: str, pool):
    """
    Подключаем все найденные сессии и записываем/обновляем данные в таблице users.
    """
    if not API_ID or not API_HASH:
        raise RuntimeError(
            "Не заданы API_ID / API_HASH в .env для Telethon аккаунтов."
        )

    sessions = load_sessions(account_path)
    clients = []

    for session in sessions:
        # Например: accounts/DE/1234567890/session.dat
        session_path_raw = session
        client = None
        try:
            client = TelegramClient(session, API_ID, API_HASH)
            await client.connect()

            # Структура: accounts/COUNTRY/NUMBER/<file>
            session_path = client.session.filename
            user_number = os.path.basename(os.path.dirname(session_path))
            user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))

            account_label = f"{user_country}/{user_number}"

            if await client.is_user_authorized():
                me = await client.get_me()

                user_id = me.id
                user_name = (me.first_name or "") + (
                    f" {me.last_name}" if getattr(me, "last_name", None) else ""
                )
                user_bio = getattr(me, "about", None)

                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        # Проверяем, есть ли уже пользователь
                        await cur.execute(
                            "SELECT id FROM users WHERE user_id = %s",
                            (user_id,),
                        )
                        existing = await cur.fetchone()

                        if not existing:
                            await cur.execute(
                                """
                                INSERT INTO users
                                (user_number, user_id, user_name, user_bio, user_country, user_status)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    int(user_number),
                                    user_id,
                                    user_name,
                                    user_bio,
                                    user_country,
                                    "off",
                                ),
                            )
                            logger.info("💾 [%s] добавлен в users | %s", account_label, user_name)
                        else:
                            # Обновляем базовую информацию.
                            # user_bio обновляем только если Telegram вернул непустое значение,
                            # иначе оставляем старое (через COALESCE).
                            await cur.execute(
                                """
                                UPDATE users
                                SET user_number = %s,
                                    user_name = %s,
                                    user_bio = COALESCE(%s, user_bio),
                                    user_country = %s
                                WHERE user_id = %s
                                """,
                                (
                                    int(user_number),
                                    user_name,
                                    user_bio,
                                    user_country,
                                    user_id,
                                ),
                            )
                            logger.info("ℹ️ [%s] обновлён в users | %s", account_label, user_name)

                clients.append(client)
                logger.info("✅ [%s] клиент подключён", account_label)
                # Подключаем обработчик входящих личных сообщений
                attach_private_message_handler(client, pool)
            else:
                logger.warning("❌ [%s] не авторизован", account_label)
                # Отмечаем в БД, что аккаунт проблемный
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE users
                            SET user_status = 'error'
                            WHERE user_country = %s AND user_number = %s
                            """,
                            (user_country, int(user_number)),
                        )
                # Отключаем клиент, так как использовать его не будем
                await client.disconnect()

        except Exception as exc:  # noqa: BLE001
            logger.warning("❌ Ошибка для сессии %s: %s", session, exc)
            # Помечаем аккаунт как error, если можем определить страну и номер
            try:
                user_number = os.path.basename(os.path.dirname(session_path_raw))
                user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path_raw)))
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE users
                            SET user_status = 'error'
                            WHERE user_country = %s AND user_number = %s
                            """,
                            (user_country, int(user_number)),
                        )
            except Exception:
                pass
            # Пытаемся корректно отключить клиента, если он успел создаться
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    logger.info("Итого подключено аккаунтов: %s", len(clients))
    return clients

