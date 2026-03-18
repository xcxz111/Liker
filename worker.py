import asyncio
import os
import random
from collections import Counter
from datetime import datetime

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException
from telethon import functions, types
from telethon.errors import (
    FloodWaitError,
    UserAlreadyParticipantError,
    ChannelPrivateError,
    InviteHashInvalidError,
)
from telethon.tl.functions.channels import JoinChannelRequest


REACTIONS = ["😘", "❤️", "😍", "🥰", "🔥", "😱", "🤩", "💯"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_LINKS_PATH = os.path.join(BASE_DIR, "data", "chat_links.txt")
CHANNEL_LINKS_PATH = os.path.join(BASE_DIR, "data", "channel_links.txt")

# Делает результаты langdetect детерминированными между запусками
DetectorFactory.seed = 0

# Набор разных цветов для аккаунтов
ACCOUNT_COLORS = [
    "\033[31m",  # красный
    "\033[32m",  # зелёный
    "\033[33m",  # жёлтый
    "\033[34m",  # синий
    "\033[35m",  # фиолетовый
    "\033[36m",  # бирюзовый
    "\033[91m",  # ярко-красный
    "\033[92m",  # ярко-зелёный
    "\033[94m",  # ярко-синий
]
RESET_COLOR = "\033[0m"


def colorize_account_label(account_label: str) -> str:
    """
    Возвращает аккаунт с цветом, выбранным по хэшу.
    Так даже при 100–200 аккаунтах цвета будут равномерно распределены.
    """
    idx = hash(account_label) % len(ACCOUNT_COLORS)
    color = ACCOUNT_COLORS[idx]
    return f"{color}{account_label}{RESET_COLOR}"


async def get_and_remove_link(file_lock: asyncio.Lock, path: str):
    async with file_lock:
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            links = f.readlines()

        if not links:
            return None

        link = links[0].strip()
        link = link.replace('"', "").replace(",", "")

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(links[1:])

        return link or None


def detect_chat_language(messages):
    """
    Определяем основной язык чата по последним текстовым сообщениям.
    Используем langdetect и считаем преобладающий язык по отдельным сообщениям.
    """
    texts: list[str] = []
    for m in messages:
        msg = getattr(m, "message", None)
        if not msg:
            continue
        # Отбрасываем совсем короткие фрагменты, по ним детектор часто ошибается
        normalized = msg.strip()
        if len(normalized) < 10:
            continue
        texts.append(normalized)

    if not texts:
        return None

    counts: Counter[str] = Counter()
    for t in texts:
        try:
            code = detect(t)  # например: "de", "fr", "ar", "zh-cn"
        except LangDetectException:
            continue
        if not code:
            continue
        base_code = code.split("-")[0].upper()
        counts[base_code] += 1

    if not counts:
        return None

    # Берём язык с максимальным количеством "голосов"
    lang, cnt = counts.most_common(1)[0]

    # Если сообщений слишком мало или разброс большой, можно не доверять результату
    total = sum(counts.values())
    if total < 3:
        return None
    share = cnt / total
    if share < 0.4:
        # нет явно доминирующего языка
        return None

    return lang


async def purge_dialogs_and_channels(client, colored_label: str):
    """
    При достижении лимитов Telegram:
    - выходим из всех каналов,
    - очищаем историю всех диалогов (лички и чаты).
    Запускается один раз на клиента.
    """
    if getattr(client, "_purged_dialogs", False):
        return

    from telethon.tl.functions.channels import LeaveChannelRequest
    from telethon.tl.functions.messages import DeleteHistoryRequest

    client._purged_dialogs = True
    print(f"⚠️ {colored_label} достиг лимитов, очищаем каналы и диалоги...")

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        name = getattr(entity, "title", None) or getattr(entity, "first_name", None) or "unknown"
        try:
            if isinstance(entity, types.Channel):
                await client(LeaveChannelRequest(entity))
                print(f"🚪 {colored_label} вышел из канала '{name}'")
            else:
                await client(
                    DeleteHistoryRequest(
                        peer=entity,
                        max_id=0,
                        revoke=True,
                    )
                )
                print(f"🗑 {colored_label} очистил диалог '{name}'")
        except Exception as e:
            print(f"⚠️ {colored_label} не смог очистить '{name}': {e}")


async def get_chat_metadata(client, chat):
    """
    Получаем доп. данные о чате:
    - описание
    - дату создания (по возможности)
    - статус (public/private)
    - количество пользователей
    """
    chat_description = None
    chat_created_at = getattr(chat, "date", None)
    chat_status = "public" if getattr(chat, "username", None) else "private"
    user_count = None

    try:
        # Каналы / супергруппы
        if isinstance(chat, types.Channel):
            full = await client(functions.channels.GetFullChannelRequest(channel=chat))
            full_chat = getattr(full, "full_chat", None)
            if full_chat:
                chat_description = getattr(full_chat, "about", None)
                user_count = getattr(full_chat, "participants_count", None)
        # Обычные чаты
        elif isinstance(chat, types.Chat):
            full = await client(functions.messages.GetFullChatRequest(chat_id=chat.id))
            full_chat = getattr(full, "full_chat", None)
            if full_chat:
                chat_description = getattr(full_chat, "about", None)
                user_count = getattr(full_chat, "participants_count", None)
    except Exception as e:
        print(f"⚠️ Не удалось получить полную информацию о чате: {e}")

    return chat_description, chat_created_at, chat_status, user_count


async def ensure_joined(client, chat) -> bool:
    """
    Пытаемся вступить в чат, если ещё не участник.
    """
    session_path = client.session.filename
    account_number = os.path.basename(os.path.dirname(session_path))
    country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))
    account_label = f"{country}/{account_number}"
    colored_label = colorize_account_label(account_label)

    chat_name_for_log = getattr(chat, "title", None) or getattr(
        chat, "first_name", None
    ) or str(getattr(chat, "id", "unknown"))

    try:
        await client(JoinChannelRequest(chat))
        print(f"➕ {colored_label} вступил в чат '{chat_name_for_log}'")
        return True
    except UserAlreadyParticipantError:
        print(f"ℹ️ {colored_label} уже был участником чата '{chat_name_for_log}'")
        return False
    except Exception as e:
        # если заявка на вступление или приватный канал
        if "requested to join" in str(e):
            print(f"📨 {colored_label} отправил заявку на вступление в '{chat_name_for_log}'")
            # Считаем "как вступили" по логике пауз: чтобы не долбить чат дальше,
            # пока Telegram не одобрит заявку.
            return True
        else:
            err = str(e)
            # При лимитах очищаем каналы и диалоги
            if "CHANNELS_TOO_MUCH" in err or "DIALOGS_TOO_MUCH" in err:
                print(
                    f"⚠️ {colored_label} достиг лимита по каналам/диалогам при вступлении "
                    f"в '{chat_name_for_log}': {err}"
                )
                await purge_dialogs_and_channels(client, colored_label)
            print(f"❌ {colored_label} ошибка вступления в '{chat_name_for_log}': {e}")
        return False


async def send_reaction(client, peer, message_id: int):
    """
    Ставим реакцию: сначала из нашего списка, если нельзя — пробуем более простую.
    Возвращаем эмодзи, если реакция поставлена, иначе None.
    """
    # сначала пробуем из нашего списка
    emoji = random.choice(REACTIONS)
    try:
        await client(
            functions.messages.SendReactionRequest(
                peer=peer,
                msg_id=message_id,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
            )
        )
        return emoji
    except Exception:
        # пробуем что-то более базовое
        for fallback in ["👍", "❤️", "🔥"]:
            try:
                await client(
                    functions.messages.SendReactionRequest(
                        peer=peer,
                        msg_id=message_id,
                        reaction=[types.ReactionEmoji(emoticon=fallback)],
                    )
                )
                return fallback
            except Exception:
                continue

    return None


async def process_channel_link(
    client,
    pool,
    file_lock: asyncio.Lock,
    channel_link: str,
    colored_label: str,
    account_id: int,
    user_country: str,
):
    """
    Обработка одной ссылки на канал из файла channel_links.txt.
    """
    try:
        channel = await client.get_entity(channel_link)
    except Exception as e:
        print(f"❌ Невозможно получить канал по ссылке {channel_link}: {e}")
        return

    if not isinstance(channel, (types.Channel, types.Chat)):
        print(f"❌ {colored_label} ссылка {channel_link} не является каналом/чатом")
        return

    channel_name_for_log = getattr(channel, "title", None) or str(channel_link)

    # Сохраняем или обновляем запись в таблице channels
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_country, last_liked_post_id, last_liked_message_id
                FROM channels
                WHERE channel_link = %s
                """,
                (channel_link,),
            )
            row = await cur.fetchone()

    internal_channel_id = None
    channel_country_db = None
    last_liked_post_id_db = None
    last_liked_message_id_db = None

    if not row:
        channel_name = getattr(channel, "title", None)
        channel_username = getattr(channel, "username", None)
        (
            channel_description,
            channel_created_at,
            channel_status,
            user_count,
        ) = await get_chat_metadata(client, channel)

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO channels
                    (channel_name, channel_username, channel_link, channel_description,
                     channel_created_at, channel_status, channel_comments, user_count, channel_country)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        channel_name,
                        channel_username,
                        channel_link,
                        channel_description,
                        channel_created_at,
                        channel_status,
                        0,  # channel_comments пока 0, обновим ниже
                        user_count,
                        None,
                    ),
                )
                internal_channel_id = cur.lastrowid
        print(f"💾 Канал добавлен в БД: {channel_name_for_log}")
    else:
        internal_channel_id, channel_country_db, last_liked_post_id_db, last_liked_message_id_db = row

    # Получаем последние 10 постов канала (пытаемся без вступления)
    joined = False
    try:
        posts = await client.get_messages(channel, limit=10)
    except ChannelPrivateError as e:
        # Закрытый канал — отправляем запрос на вступление и пробуем ещё раз
        print(f"ℹ️ {colored_label} не может читать канал без вступления: {e}")
        joined = await ensure_joined(client, channel)
        try:
            posts = await client.get_messages(channel, limit=10)
        except Exception as e2:
            print(f"❌ Не удалось получить посты канала даже после вступления: {e2}")
            return
    except Exception as e:
        print(f"❌ Не удалось получить посты канала: {e}")
        return

    text_posts = [m for m in posts if m.message and not m.action]

    # Определяем язык канала по последним постам
    channel_country = detect_chat_language(text_posts)
    if channel_country:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE channels SET channel_country = %s WHERE id = %s",
                    (channel_country, internal_channel_id),
                )
        print(
            f"🔤 {colored_label} определил язык канала '{channel_name_for_log}' как {channel_country}"
        )

    # Проверяем, можно ли оставлять комментарии
    from telethon.tl.functions import messages as msg_funcs

    can_comment = False
    last_post = posts[0] if posts else None
    if last_post:
        try:
            # Если запрос проходит без ошибки — комментарии для этого поста разрешены,
            # даже если сейчас их ещё нет.
            await client(
                msg_funcs.GetRepliesRequest(
                    peer=channel,
                    msg_id=last_post.id,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=0,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
            can_comment = True
        except ChannelPrivateError as e:
            # Для закрытого канала могли уже вступить выше; если даже после вступления
            # не можем проверять комментарии — считаем, что комментарии отключены.
            print(f"ℹ️ {colored_label} не может проверить комментарии в канале: {e}")
            can_comment = False
        except Exception:
            can_comment = False

    # Обновляем флаг channel_comments
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE channels SET channel_comments = %s WHERE id = %s",
                (1 if can_comment else 0, internal_channel_id),
            )

    if not can_comment:
        # Нет комментариев — просто спим и выходим
        if joined:
            sleep_sec = random.randint(500, 800)
            print(
                f"😴 {colored_label} (канал без комментариев) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после канала '{channel_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)
        else:
            sleep_sec = random.randint(15, 20)
            print(
                f"😴 {colored_label} (канал без комментариев, без вступления) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после канала '{channel_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)
        return

    # Работаем с комментариями к последнему посту
    if not last_post:
        return

    # Перед работой с комментариями при необходимости вступаем в канал:
    # открытый канал — вступаем только после того, как язык совпал и комментарии включены;
    # закрытый канал — мы могли уже вступить выше при чтении постов.
    if not joined:
        joined = await ensure_joined(client, channel)
    try:
        replies = await client(
            msg_funcs.GetRepliesRequest(
                peer=channel,
                msg_id=last_post.id,
                offset_id=0,
                offset_date=None,
                add_offset=0,
                limit=50,
                max_id=0,
                min_id=0,
                hash=0,
            )
        )
        comments = replies.messages or []
    except Exception as e:
        print(f"❌ Не удалось получить комментарии к посту: {e}")
        return

    # Определяем язык по комментариям
    comment_texts = [
        m for m in comments if m.message and not m.action
    ]
    comment_lang = detect_chat_language(comment_texts)
    if comment_lang:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE channels SET channel_country = %s WHERE id = %s",
                    (comment_lang, internal_channel_id),
                )
        channel_country = comment_lang

    # Если язык канала не совпадает со страной аккаунта — не вступаем, просто спим и выходим
    if not channel_country or channel_country != user_country:
        if joined:
            sleep_sec = random.randint(500, 800)
            print(
                f"😴 {colored_label} (язык канала не совпал) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после канала '{channel_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)
        else:
            sleep_sec = random.randint(15, 20)
            print(
                f"😴 {colored_label} (язык канала не совпал, без вступления) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после канала '{channel_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)
        return

    # Берём последние 20 комментариев
    # (исключая сервисные и сообщения с ссылками)
    reaction_candidates = []
    for m in comments:
        if m.action:
            continue
        text = m.message or ""
        lower = text.lower()
        if any(p in lower for p in ("http://", "https://", "t.me/")):
            continue
        reaction_candidates.append(m)

    last_20 = reaction_candidates[:20]
    if not last_20:
        return

    newest_comment = last_20[0]
    others = last_20[1:] if len(last_20) > 1 else []
    random_others = random.sample(others, min(4, len(others)))
    to_like = random_others + [newest_comment]

    # Ставим реакции на комментарии
    success_count = 0
    for msg in to_like:
        try:
            # Для комментариев peer должен быть тем же, что и у сообщения (дискуссионный чат)
            peer = getattr(msg, "peer_id", None) or channel
            emoji_used = await send_reaction(client, peer, msg.id)
            if emoji_used:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "UPDATE users SET like_count = like_count + 1 WHERE id = %s",
                            (account_id,),
                        )
                        await cur.execute(
                            """
                            UPDATE channels
                            SET last_liked_post_id = %s,
                                last_liked_message_id = %s,
                                last_like_at = %s,
                                last_account_id = %s,
                                like_count = like_count + 1
                            WHERE id = %s
                            """,
                            (
                                last_post.id,
                                msg.id,
                                datetime.utcnow(),
                                account_id,
                                internal_channel_id,
                            ),
                        )

                print(
                    f"✅ {colored_label} поставил реакцию {emoji_used} "
                    f"в канале '{channel_name_for_log}' на комментарий {msg.id} "
                    f"({'после вступления' if joined else 'без вступления'})"
                )

            await asyncio.sleep(random.randint(11, 15))
        except FloodWaitError as e:
            print(f"⏳ FloodWait {e.seconds} сек (канал)")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print("Ошибка при постановке реакции в канале:", e)

    if success_count > 0:
        print(
            f"✅ Лайки поставлены в канале '{channel_name_for_log}' аккаунтом {colored_label} "
            f"({'после вступления' if joined else 'без вступления'})"
        )
    else:
        print(
            f"⚠️ {colored_label} не смог поставить реакции в канале '{channel_name_for_log}'"
        )

    # Сон после обработки канала
    if joined:
        sleep_sec = random.randint(500, 800)
        print(
            f"😴 {colored_label} (канал, после лайков) "
            f"\033[31mспит {sleep_sec} сек\033[0m "
            f"после канала '{channel_name_for_log}'"
        )
        await asyncio.sleep(sleep_sec)
    else:
        sleep_sec = random.randint(15, 20)
        print(
            f"😴 {colored_label} (канал, после лайков, без вступления) "
            f"\033[31mспит {sleep_sec} сек\033[0m "
            f"после канала '{channel_name_for_log}'"
        )
        await asyncio.sleep(sleep_sec)


async def process_account(client, pool, file_lock: asyncio.Lock):
    """
    Основной цикл работы аккаунта:
    - берём ссылку из файла (если нет — работаем по БД);
    - работаем с чатом, определяем язык, при совпадении стран и наличии новых сообщений ставим реакции.
    """
    while True:
        # 1️⃣ Базовая информация об аккаунте для логов
        session_path = client.session.filename
        account_number = os.path.basename(os.path.dirname(session_path))
        country_from_path = os.path.basename(os.path.dirname(os.path.dirname(session_path)))
        account_label = f"{country_from_path}/{account_number}"
        colored_label = colorize_account_label(account_label)

        # 2️⃣ Получаем данные аккаунта (id, страна и статус) из БД
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, user_country, user_status FROM users WHERE user_id = %s",
                    (client._self_id,),
                )
                acc_row = await cur.fetchone()

        if not acc_row:
            # Аккаунт почему-то не нашли — останавливаем воркер
            print(f"⏹ {colored_label} остановлен: аккаунт не найден в БД")
            break

        account_id, user_country, user_status = acc_row

        # Если статус не 'on', выходим из цикла (останавливаем воркер)
        if user_status != "on":
            print(f"⏹ {colored_label} остановлен: статус {user_status}")
            break

        # 2️⃣ Сначала пробуем взять ссылку из файла чатов
        link = await get_and_remove_link(file_lock, CHAT_LINKS_PATH)
        internal_chat_id = None
        last_liked_message_id_db = None
        source = "file"

        if link:
            print(f"📂 {colored_label} работает по файлу: {link}")

            # Если такая ссылка уже есть в БД, просто пропускаем её
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id FROM chats WHERE chat_link = %s",
                        (link,),
                    )
                    existing_chat = await cur.fetchone()

            if existing_chat:
                print(
                    f"⏭ Ссылка {link} уже есть в таблице chats (id={existing_chat[0]}), пропускаем"
                )
                await asyncio.sleep(6)
                continue

        else:
            # 3️⃣ Файл чатов пуст — пробуем файл каналов
            channel_link = await get_and_remove_link(file_lock, CHANNEL_LINKS_PATH)
            if channel_link:
                print(f"📂 Работаем по файлу каналов: {channel_link}")
                await process_channel_link(
                    client,
                    pool,
                    file_lock,
                    channel_link,
                    colored_label,
                    account_id,
                    user_country,
                )
                continue

            # 4️⃣ Оба файла пусты — работаем по БД (чаты)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Берём случайный чат, где язык совпадает с аккаунтом
                    # ИЛИ язык ещё не определён (chat_country IS NULL)
                    await cur.execute(
                        """
                        SELECT id, chat_link, chat_country, last_liked_message_id
                        FROM chats
                        WHERE chat_country = %s OR chat_country IS NULL
                        ORDER BY RAND()
                        LIMIT 1
                        """,
                        (user_country,),
                    )
                    row = await cur.fetchone()

            if not row:
                print("❌ Нет подходящих чатов в БД")
                await asyncio.sleep(15)
                continue

            internal_chat_id, link, chat_country_db, last_liked_message_id_db = row
            source = "db"
            print(f"🗄 {colored_label} работает по БД: {link}")

        # 4️⃣ Получаем сущность чата по ссылке
        try:
            chat = await client.get_entity(link)
        except FloodWaitError as e:
            # Лимит на ResolveUsername/получение сущности по username
            print(
                f"⏳ {colored_label} FloodWait при получении чата {link}: "
                f"нужно ждать {e.seconds} сек"
            )
            await asyncio.sleep(e.seconds)
            continue
        except (ChannelPrivateError, InviteHashInvalidError) as e:
            print(f"❌ {colored_label} невозможно зайти по ссылке {link}: {e}")
            # Если ссылка была взята из БД и чат недоступен — удаляем запись из БД
            if source == "db" and internal_chat_id is not None:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "DELETE FROM chats WHERE id = %s",
                            (internal_chat_id,),
                        )
                        print(
                            f"🗑 {colored_label} чат с id={internal_chat_id} "
                            f"удалён из БД как битый"
                        )
            continue
        except Exception as e:
            print(f"❌ {colored_label} ошибка при получении чата {link}: {e}")
            continue

        chat_name_for_log = (
            getattr(chat, "title", None)
            or getattr(chat, "first_name", None)
            or str(link)
        )

        # 5️⃣ Сохраняем или обновляем чат в БД
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                if internal_chat_id is None:
                    # Пытаемся найти чат по ссылке
                    await cur.execute(
                        "SELECT id, chat_country, last_liked_message_id FROM chats WHERE chat_link = %s",
                        (link,),
                    )
                    row = await cur.fetchone()

                    if not row:
                        # создаём новую запись
                        chat_name = getattr(chat, "title", None) or getattr(
                            chat, "first_name", None
                        )
                        chat_username = getattr(chat, "username", None)
                        (
                            chat_description,
                            chat_created_at,
                            chat_status,
                            user_count,
                        ) = await get_chat_metadata(client, chat)

                        await cur.execute(
                            """
                            INSERT INTO chats
                            (chat_name, chat_username, chat_link, chat_description,
                             chat_created_at, chat_status, user_count, chat_country)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                chat_name,
                                chat_username,
                                link,
                                chat_description,
                                chat_created_at,
                                chat_status,
                                user_count,
                                None,
                            ),
                        )
                        internal_chat_id = cur.lastrowid
                        last_liked_message_id_db = None
                        print(f"💾 Чат добавлен в БД: {chat_name}")
                    else:
                        internal_chat_id, chat_country_db, last_liked_message_id_db = row
                else:
                    # Чат уже есть — обновляем базовую информацию
                    chat_name = getattr(chat, "title", None) or getattr(
                        chat, "first_name", None
                    )
                    chat_username = getattr(chat, "username", None)
                    (
                        chat_description,
                        chat_created_at,
                        chat_status,
                        user_count,
                    ) = await get_chat_metadata(client, chat)

                    await cur.execute(
                        """
                        UPDATE chats
                        SET chat_name = %s,
                            chat_username = %s,
                            chat_description = %s,
                            chat_created_at = %s,
                            chat_status = %s,
                            user_count = %s
                        WHERE id = %s
                        """,
                        (
                            chat_name,
                            chat_username,
                            chat_description,
                            chat_created_at,
                            chat_status,
                            user_count,
                            internal_chat_id,
                        ),
                    )

        # 6️⃣ Получаем последние 50 сообщений (пытаемся без вступления)
        joined = False
        try:
            messages = await client.get_messages(chat, limit=50)
        except Exception as e:
            print(
                f"❌ {colored_label} не удалось получить сообщения чата "
                f"'{chat_name_for_log}': {e}"
            )
            continue

        # Оставляем только текстовые, без медиа и сервисных — для определения языка
        text_messages = [
            m for m in messages if m.message and not m.media and not m.action
        ]

        # Сообщения-кандидаты для реакций:
        # - любые, где нет сервисного действия (m.action is None)
        # - и в тексте НЕТ ссылок (http, https, t.me и т.п.)
        # Можно ставить реакции на медиа (фото, аудио, голосовые) и обычные тексты без ссылок.
        reaction_messages = []
        for m in messages:
            if m.action:
                continue
            text = m.message or ""
            lower = text.lower()
            if any(p in lower for p in ("http://", "https://", "t.me/")):
                continue
            reaction_messages.append(m)

        # Определяем язык
        chat_country = detect_chat_language(text_messages)

        # Обновляем язык в БД (только если смогли определить)
        if chat_country:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE chats SET chat_country = %s WHERE id = %s",
                        (chat_country, internal_chat_id),
                    )
            print(
                f"🔤 {colored_label} определил язык чата '{chat_name_for_log}' как {chat_country}"
            )

        # Если язык не смогли определить — вступаем (чтобы в будущем было больше данных) и спим
        if not chat_country:
            joined = await ensure_joined(client, chat)
            if joined:
                sleep_sec = random.randint(500, 800)
                print(
                    f"😴 {colored_label} (язык не определён) "
                    f"\033[31mспит {sleep_sec} сек\033[0m "
                    f"после чата '{chat_name_for_log}'"
                )
                await asyncio.sleep(sleep_sec)
            else:
                sleep_sec = random.randint(10, 20)
                print(
                    f"😴 {colored_label} (язык не определён, без вступления) "
                    f"\033[31mспит {sleep_sec} сек\033[0m "
                    f"после чата '{chat_name_for_log}'"
                )
                await asyncio.sleep(sleep_sec)
            continue

        # Если страна совпала и язык определён — при необходимости вступаем и работаем
        if chat_country and user_country == chat_country:
            if not joined:
                joined = await ensure_joined(client, chat)
            # последние 20 сообщений-кандидатов для реакций (Telethon возвращает от новых к старым)
            last_20 = reaction_messages[:20]
            if not last_20:
                await asyncio.sleep(10)
                continue

            # Самое новое сообщение в чате
            newest_msg = last_20[0]

            # проверяем, что есть минимум 20 новых сообщений после последней реакции (для работы по БД)
            if source == "db" and last_liked_message_id_db:
                last_msg_id = newest_msg.id
                if last_msg_id - last_liked_message_id_db <= 20:
                    # недостаточно новых сообщений — просто спим и берём следующий чат
                    if joined:
                        sleep_sec = random.randint(500, 800)
                        print(
                            f"😴 {colored_label} (мало новых сообщений) "
                            f"\033[31mспит {sleep_sec} сек\033[0m "
                            f"после чата '{chat_name_for_log}'"
                        )
                        await asyncio.sleep(sleep_sec)
                    else:
                        sleep_sec = random.randint(10, 20)
                        print(
                            f"😴 {colored_label} (мало новых сообщений, без вступления) "
                            f"\033[31mспит {sleep_sec} сек\033[0m "
                            f"после чата '{chat_name_for_log}'"
                        )
                        await asyncio.sleep(sleep_sec)
                    continue

            # 4 реакции — по рандомным сообщениям из последних 20 (кроме самого нового),
            # 5‑я реакция — на самое новое сообщение в чате
            others = last_20[1:] if len(last_20) > 1 else []
            random_others = random.sample(others, min(4, len(others)))
            to_like = random_others + [newest_msg]

            success_count = 0
            for msg in to_like:
                try:
                    emoji_used = await send_reaction(client, chat, msg.id)
                    if emoji_used:
                        # Обновляем счётчики в БД (только при успешной реакции)
                        async with pool.acquire() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(
                                    "UPDATE users SET like_count = like_count + 1 WHERE id = %s",
                                    (account_id,),
                                )
                                await cur.execute(
                                    """
                                    UPDATE chats
                                    SET last_liked_message_id = %s,
                                        last_like_at = %s,
                                        last_account_id = %s,
                                        like_count = like_count + 1
                                    WHERE id = %s
                                    """,
                                    (
                                        msg.id,
                                        datetime.utcnow(),
                                        account_id,
                                        internal_chat_id,
                                    ),
                                )

                        print(
                            f"✅ {colored_label} поставил реакцию {emoji_used} "
                            f"в чате '{chat_name_for_log}' на сообщение {msg.id} "
                            f"({'после вступления' if joined else 'без вступления'})"
                        )
                        success_count += 1

                    # Чуть увеличиваем паузу между реакциями, чтобы реже ловить flood wait
                    await asyncio.sleep(random.randint(11, 15))
                except FloodWaitError as e:
                    print(f"⏳ FloodWait {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print("Ошибка при постановке реакции:", e)

            if success_count > 0:
                print(
                    f"✅ Лайки поставлены в чате '{chat_name_for_log}' аккаунтом {colored_label} "
                    f"({'после вступления' if joined else 'без вступления'})"
                )
            else:
                print(
                    f"⚠️ {colored_label} не смог поставить реакции в чате '{chat_name_for_log}'"
                )

        else:
            # Язык не совпал — просто спим и берём следующую ссылку
            if joined:
                sleep_sec = random.randint(500, 800)
                print(
                    f"😴 {colored_label} (язык не совпал) "
                    f"\033[31mспит {sleep_sec} сек\033[0m "
                    f"после чата '{chat_name_for_log}'"
                )
                await asyncio.sleep(sleep_sec)
            else:
                sleep_sec = random.randint(10, 20)
                print(
                    f"😴 {colored_label} (язык не совпал, без вступления) "
                    f"\033[31mспит {sleep_sec} сек\033[0m "
                    f"после чата '{chat_name_for_log}'"
                )
                await asyncio.sleep(sleep_sec)
            continue

        # Сон после обработки чата, когда ставили реакции
        if joined:
            sleep_sec = random.randint(500, 800)
            print(
                f"😴 {colored_label} (после лайков) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после чата '{chat_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)
        else:
            sleep_sec = random.randint(10, 20)
            print(
                f"😴 {colored_label} (после лайков, без вступления) "
                f"\033[31mспит {sleep_sec} сек\033[0m "
                f"после чата '{chat_name_for_log}'"
            )
            await asyncio.sleep(sleep_sec)

