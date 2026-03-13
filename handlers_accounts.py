import os
import asyncio
import shutil

from aiogram import Router, F, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from telethon.tl.functions.account import UpdateProfileRequest

from keyboards import (
    main_keyboard,
    countries_keyboard,
    accounts_keyboard,
    account_actions_keyboard,
    stats_keyboard,
    stats_chats_keyboard,
    stats_channels_keyboard,
)


router = Router()


class AccountStates(StatesGroup):
    change_name = State()
    change_bio = State()
    change_message = State()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я бот-лайкер.\nВыберите действие:",
        reply_markup=main_keyboard(),
    )


@router.callback_query(F.data == "main_menu")
@router.callback_query(F.data == "back_main")
async def main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Привет! Я бот-лайкер.\nВыберите действие:",
        reply_markup=main_keyboard(),
    )


@router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Меню статистики: показывает кнопки для чатов и каналов с общим количеством.
    """
    pool = dispatcher["db"]

    chats_total = chats_likes = 0
    channels_total = channels_likes = 0

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # chats
            await cur.execute("SELECT COUNT(*), SUM(like_count) FROM chats")
            row = await cur.fetchone()
            if row:
                chats_total = row[0] or 0
                chats_likes = row[1] or 0

            # channels
            await cur.execute("SELECT COUNT(*), SUM(like_count) FROM channels")
            row = await cur.fetchone()
            if row:
                channels_total = row[0] or 0
                channels_likes = row[1] or 0

    await callback.message.edit_text(
        "📊 Статистика\nВыберите раздел:",
        reply_markup=stats_keyboard(chats_total, channels_total),
    )


@router.callback_query(F.data == "stats_chats")
async def show_stats_chats(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Статистика по чатам: количество чатов по языкам.
    """
    pool = dispatcher["db"]

    lang_counts: dict[str, int] = {}

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT chat_country, COUNT(*)
                FROM chats
                GROUP BY chat_country
                """
            )
            rows = await cur.fetchall()

    for chat_country, count in rows or []:
        if chat_country is None:
            key = "язык не установлен"
        else:
            key = chat_country
        lang_counts[key] = lang_counts.get(key, 0) + (count or 0)

    if not lang_counts:
        await callback.message.edit_text(
            "📊 Статистика по чатам\nЧатов пока нет.",
            reply_markup=stats_keyboard(0, 0),
        )
        return

    await callback.message.edit_text(
        "📊 Статистика по чатам\nПо языкам:",
        reply_markup=stats_chats_keyboard(lang_counts),
    )


@router.callback_query(F.data == "stats_channels")
async def show_stats_channels(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Статистика по каналам: количество каналов по языкам,
    учитываем только каналы, где включены комментарии (channel_comments = 1).
    """
    pool = dispatcher["db"]

    lang_counts: dict[str, int] = {}

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_country, COUNT(*)
                FROM channels
                WHERE channel_comments = 1
                GROUP BY channel_country
                """
            )
            rows = await cur.fetchall()

    for channel_country, count in rows or []:
        if channel_country is None:
            key = "язык не установлен"
        else:
            key = channel_country
        lang_counts[key] = lang_counts.get(key, 0) + (count or 0)

    if not lang_counts:
        await callback.message.edit_text(
            "📊 Статистика по каналам\nКаналов с включёнными комментариями пока нет.",
            reply_markup=stats_keyboard(0, 0),
        )
        return

    await callback.message.edit_text(
        "📊 Статистика по каналам\nПо языкам (только с комментариями):",
        reply_markup=stats_channels_keyboard(lang_counts),
    )


@router.callback_query(F.data == "accounts_menu")
async def show_countries(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    base_path = os.getenv("COUNTRY_FOLDER", "accounts")

    if not os.path.isdir(base_path):
        await callback.answer("Папка с аккаунтами не найдена", show_alert=True)
        return

    # Список стран из файловой системы
    fs_countries: set[str] = set()
    for entry in os.listdir(base_path):
        full_path = os.path.join(base_path, entry)
        if os.path.isdir(full_path):
            fs_countries.add(entry)

    # Определяем по странам:
    # - total: количество аккаунтов по файловой системе (папки внутри страны)
    # - enabled: количество включённых аккаунтов по БД (user_status = 'on')
    countries: dict[str, tuple[int, int]] = {}
    pool = dispatcher["db"]
    total_all = 0
    enabled_all = 0

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for country_name in sorted(fs_countries):
                country_path = os.path.join(base_path, country_name)
                # считаем аккаунты как папки внутри страны
                total = 0
                for entry in os.listdir(country_path):
                    full = os.path.join(country_path, entry)
                    if os.path.isdir(full):
                        total += 1

                await cur.execute(
                    "SELECT COUNT(*) FROM users WHERE user_country = %s AND user_status = 'on'",
                    (country_name,),
                )
                row = await cur.fetchone()
                enabled = row[0] if row else 0

                countries[country_name] = (total, enabled)
                total_all += total
                enabled_all += enabled

    if not countries:
        await callback.answer("Страны с аккаунтами не найдены", show_alert=True)
        return

    # Текст статуса для верхнего меню
    if total_all == 0:
        status_text = "Статус: аккаунты не найдены"
    elif enabled_all == 0:
        status_text = f"Статус: все аккаунты выключены 🔴 (0/{total_all})"
    elif enabled_all == total_all:
        status_text = f"Статус: все аккаунты включены 🟢 ({enabled_all}/{total_all})"
    else:
        status_text = (
            f"Статус: аккаунты включены частично 🔵 "
            f"({enabled_all}/{total_all})"
        )

    try:
        await callback.message.edit_text(
            f"Страны аккаунтов\n{status_text}",
            reply_markup=countries_keyboard(countries, total_all, enabled_all),
        )
    except TelegramBadRequest as e:
        # Игнорируем ситуацию, когда текст и клавиатура не меняются
        if "message is not modified" not in str(e):
            raise


@router.callback_query(F.data.startswith("country:"))
async def show_accounts(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    _, country = callback.data.split(":", 1)
    base_path = os.getenv("COUNTRY_FOLDER", "accounts")
    country_path = os.path.join(base_path, country)

    if not os.path.isdir(country_path):
        await callback.answer("Папка страны не найдена", show_alert=True)
        return

    accounts: list[str] = []
    # предполагаем структуру accounts/COUNTRY/ACCOUNT/...
    for entry in os.listdir(country_path):
        full_path = os.path.join(country_path, entry)
        if os.path.isdir(full_path):
            accounts.append(entry)

    if not accounts:
        await callback.answer("Аккаунты в этой стране не найдены", show_alert=True)
        return

    # Определяем, сколько аккаунтов страны включено и их статусы по номерам
    pool = dispatcher["db"]
    status_by_number: dict[str, str] = {}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT user_number, user_status FROM users WHERE user_country = %s",
                (country,),
            )
            rows = await cur.fetchall()

    total = 0
    on_count = 0
    for user_number, user_status in rows or []:
        acc_name = str(user_number)
        status_by_number[acc_name] = user_status
        total += 1
        if user_status == "on":
            on_count += 1

    await callback.message.edit_text(
        f"Страна: {country}\n"
        f"Статус: включено {on_count} из {total}\n"
        f"Выберите аккаунт:",
        reply_markup=accounts_keyboard(country, accounts, total, on_count, status_by_number),
    )


@router.callback_query(F.data == "back_countries")
async def back_to_countries(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    # Переиспользуем логику показа стран
    await show_countries(callback, dispatcher)


@router.callback_query(F.data.startswith("acc:"))
async def account_menu(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Меню конкретного аккаунта: изменить имя/bio/фото/сообщение.
    """
    _, country, account = callback.data.split(":", 2)

    # Берём данные аккаунта из БД
    pool = dispatcher["db"]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT user_name, user_bio, user_message, user_status
                FROM users
                WHERE user_country = %s AND user_number = %s
                """,
                (country, int(account)),
            )
            row = await cur.fetchone()

    if row:
        user_name, user_bio, user_message, user_status = row
    else:
        user_name, user_bio, user_message, user_status = None, None, None, None

    name_text = user_name or "—"
    bio_text = user_bio or "—"
    msg_text = user_message or "—"

    if user_status == "on":
        status_text = "включен 🟢"
    elif user_status == "error":
        status_text = "ошибка ❌"
    else:
        status_text = "выключен 🔴"

    await callback.message.edit_text(
        f"Аккаунт {country}/{account}\n"
        f"Имя: {name_text}\n"
        f"Bio: {bio_text}\n"
        f"Сообщение: {msg_text}\n"
        f"Статус: {status_text}\n\n"
        f"Выберите действие:",
        reply_markup=account_actions_keyboard(country, account, user_status),
    )


@router.callback_query(F.data.startswith("back_accounts:"))
async def back_to_accounts_from_actions(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Возврат из меню действий аккаунта к списку аккаунтов страны.
    """
    _, country = callback.data.split(":", 1)
    base_path = os.getenv("COUNTRY_FOLDER", "accounts")
    country_path = os.path.join(base_path, country)

    if not os.path.isdir(country_path):
        await callback.answer("Папка страны не найдена", show_alert=True)
        return

    accounts: list[str] = []
    for entry in os.listdir(country_path):
        full_path = os.path.join(country_path, entry)
        if os.path.isdir(full_path):
            accounts.append(entry)

    if not accounts:
        await callback.answer("Аккаунты в этой стране не найдены", show_alert=True)
        return

    # Определяем, сколько аккаунтов страны включено и их статусы по номерам
    pool = dispatcher["db"]
    status_by_number: dict[str, str] = {}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT user_number, user_status FROM users WHERE user_country = %s",
                (country,),
            )
            rows = await cur.fetchall()

    total = 0
    on_count = 0
    for user_number, user_status in rows or []:
        acc_name = str(user_number)
        status_by_number[acc_name] = user_status
        total += 1
        if user_status == "on":
            on_count += 1

    await callback.message.edit_text(
        f"Страна: {country}\n"
        f"Статус: включено {on_count} из {total}\n"
        f"Выберите аккаунт:",
        reply_markup=accounts_keyboard(country, accounts, total, on_count, status_by_number),
    )


@router.callback_query(F.data.startswith("acc_action:"))
async def account_action_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработчик действий аккаунта.
    Пока реализовано только изменение имени.
    """
    _, action, country, account = callback.data.split(":", 3)

    if action == "name":
        # Сохраняем информацию об аккаунте в состояние и просим ввести имя
        await state.update_data(country=country, account=account)
        await state.set_state(AccountStates.change_name)
        await callback.message.edit_text(
            f"Аккаунт {country}/{account}\n"
            f"Введите новое имя или имя и фамилию через пробел:",
            reply_markup=None,
        )
        await callback.answer()
        return

    if action == "bio":
        # Сохраняем информацию об аккаунте в состояние и просим ввести bio
        await state.update_data(country=country, account=account)
        await state.set_state(AccountStates.change_bio)
        await callback.message.edit_text(
            f"Аккаунт {country}/{account}\n"
            f"Введите новое bio (до 70 символов):",
            reply_markup=None,
        )
        await callback.answer()
        return

    if action == "message":
        # Сохраняем информацию об аккаунте в состояние и просим ввести сообщение
        await state.update_data(country=country, account=account)
        await state.set_state(AccountStates.change_message)
        await callback.message.edit_text(
            f"Аккаунт {country}/{account}\n"
            f"Введите новое сообщение (любой текст):",
            reply_markup=None,
        )
        await callback.answer()
        return

    # Остальные действия пока как заглушки
    action_names = {
        "bio": "изменение bio",
        "photo": "изменение фото",
        "message": "изменение сообщения",
    }
    text = action_names.get(action, action)
    await callback.answer(f"{text.capitalize()} пока не реализовано", show_alert=True)


@router.message(AccountStates.change_name)
async def process_change_name(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    """
    Обработка ввода нового имени для выбранного аккаунта.
    """
    data = await state.get_data()
    country = data.get("country")
    account = data.get("account")

    new_name_raw = (message.text or "").strip()
    if not new_name_raw:
        await message.answer("Имя не может быть пустым. Введите имя ещё раз.")
        return

    # Разделяем на имя и фамилию
    if " " in new_name_raw:
        first_name, last_name = new_name_raw.split(" ", 1)
    else:
        first_name, last_name = new_name_raw, ""

    clients = dispatcher["clients"]
    target_client = None

    for client in clients:
        session_path = client.session.filename
        user_number = os.path.basename(os.path.dirname(session_path))
        user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))

        if user_country == country and user_number == account:
            target_client = client
            break

    if not target_client:
        await message.answer("Не удалось найти подключённый клиент для этого аккаунта.")
        await state.clear()
        return

    try:
        await target_client(
            UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name,
            )
        )

        # Обновляем имя в БД
        pool = dispatcher["db"]
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE users
                    SET user_name = %s
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (new_name_raw, country, int(account)),
                )

        # Узнаём актуальный статус для кнопки
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT user_status
                    FROM users
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (country, int(account)),
                )
                row = await cur.fetchone()
        user_status = row[0] if row else None

        await message.answer(
            f"✅ Имя аккаунта {country}/{account} изменено на: {new_name_raw}",
            reply_markup=account_actions_keyboard(country, account, user_status),
        )
    except Exception as e:
        # Узнаём статус, даже если имя не изменилось
        pool = dispatcher["db"]
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT user_status
                    FROM users
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (country, int(account)),
                )
                row = await cur.fetchone()
        user_status = row[0] if row else None

        await message.answer(
            f"❌ Не удалось изменить имя: {e}",
            reply_markup=account_actions_keyboard(country, account, user_status),
        )

    await state.clear()


@router.callback_query(F.data.startswith("acc_toggle:"))
async def account_toggle_handler(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Вкл/Выкл одного аккаунта:
    - меняем user_status между on/off
    - при включении запускаем воркер, если он ещё не запущен
    """
    from accounts.worker import process_account  # локальный импорт

    _, country, account = callback.data.split(":", 2)

    pool = dispatcher["db"]
    clients = dispatcher["clients"]
    file_lock = dispatcher["file_lock"]
    client_tasks = dispatcher.get("client_tasks", {})

    # Узнаём текущий статус
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT user_status
                FROM users
                WHERE user_country = %s AND user_number = %s
                """,
                (country, int(account)),
            )
            row = await cur.fetchone()

    current_status = row[0] if row else None

    # Определяем новый статус
    if current_status == "on":
        new_status = "off"
    else:
        new_status = "on"

    # Обновляем статус
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE users
                SET user_status = %s
                WHERE user_country = %s AND user_number = %s
                """,
                (new_status, country, int(account)),
            )

    # Если включаем, запускаем воркер для этого аккаунта (если не запущен)
    if new_status == "on":
        target_client = None
        for client in clients:
            session_path = client.session.filename
            user_number = os.path.basename(os.path.dirname(session_path))
            user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))
            if user_country == country and user_number == account:
                target_client = client
                break

        if target_client:
            key = target_client.session.filename
            task = client_tasks.get(key)
            if task is None or task.done():
                client_tasks[key] = asyncio.create_task(
                    process_account(target_client, pool, file_lock)
                )

    # Перерисовываем меню аккаунта
    dummy_cb = type(
        "DummyCb",
        (),
        {
            "data": f"acc:{country}:{account}",
            "message": callback.message,
        },
    )()
    await account_menu(dummy_cb, dispatcher)


@router.callback_query(F.data.startswith("acc_delete:"))
async def account_delete_prompt(callback: CallbackQuery) -> None:
    """
    Показываем подтверждение удаления аккаунта.
    """
    _, country, account = callback.data.split(":", 2)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить",
                    callback_data=f"acc_delete_confirm:yes:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нет",
                    callback_data=f"acc_delete_confirm:no:{country}:{account}",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить аккаунт {country}/{account}?\n"
        f"Будет удалена папка с сессией и запись в БД.",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("acc_delete_confirm:"))
async def account_delete_confirm(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Обработка подтверждения удаления аккаунта.
    """
    _, answer, country, account = callback.data.split(":", 3)

    if answer == "no":
        # Возвращаемся в меню аккаунта
        await account_menu(
            type(
                "DummyCb",
                (),
                {
                    "data": f"acc:{country}:{account}",
                    "message": callback.message,
                    "bot": callback.bot,
                },
            )(),
        )
        return

    # answer == "yes"
    pool = dispatcher["db"]
    clients = dispatcher["clients"]
    client_tasks = dispatcher.get("client_tasks", {})

    # Останавливаем воркер и отключаем клиента (если есть)
    target_client = None
    for client in clients:
        session_path = client.session.filename
        user_number = os.path.basename(os.path.dirname(session_path))
        user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))
        if user_country == country and user_number == account:
            target_client = client
            break

    if target_client:
        key = target_client.session.filename
        task = client_tasks.get(key)
        if task and not task.done():
            task.cancel()
        try:
            await target_client.disconnect()
        except Exception:
            pass
        # Убираем клиента из списка
        try:
            clients.remove(target_client)
        except ValueError:
            pass

    # Удаляем запись из БД
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM users
                WHERE user_country = %s AND user_number = %s
                """,
                (country, int(account)),
            )

    # Удаляем папку с аккаунтом
    base_path = os.getenv("COUNTRY_FOLDER", "accounts")
    acc_path = os.path.join(base_path, country, account)
    try:
        if os.path.isdir(acc_path):
            shutil.rmtree(acc_path)
    except Exception as e:
        await callback.message.edit_text(
            f"Аккаунт {country}/{account} удалён из БД, "
            f"но не удалось удалить папку: {e}",
        )
        return

    # После успешного удаления показываем список аккаунтов этой страны
    await show_accounts(
        type(
            "DummyCb",
            (),
            {
                "data": f"country:{country}",
                "message": callback.message,
            },
        )(),
        dispatcher,
    )

@router.message(AccountStates.change_bio)
async def process_change_bio(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    """
    Обработка ввода нового bio для выбранного аккаунта.
    """
    data = await state.get_data()
    country = data.get("country")
    account = data.get("account")

    new_bio = (message.text or "").strip()
    if not new_bio:
        await message.answer("Bio не может быть пустым. Введите текст ещё раз (до 70 символов).")
        return

    if len(new_bio) > 70:
        await message.answer(
            f"Слишком длинное bio ({len(new_bio)} символов). "
            f"Пожалуйста, введите текст не длиннее 70 символов."
        )
        return

    clients = dispatcher["clients"]
    target_client = None

    for client in clients:
        session_path = client.session.filename
        user_number = os.path.basename(os.path.dirname(session_path))
        user_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))

        if user_country == country and user_number == account:
            target_client = client
            break

    if not target_client:
        await message.answer(
            "Не удалось найти подключённый клиент для этого аккаунта.",
            reply_markup=account_actions_keyboard(country, account),
        )
        await state.clear()
        return

    try:
        await target_client(
            UpdateProfileRequest(
                about=new_bio,
            )
        )

        # Обновляем bio в БД
        pool = dispatcher["db"]
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE users
                    SET user_bio = %s
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (new_bio, country, int(account)),
                )

        # Узнаём статус для кнопки
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT user_status
                    FROM users
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (country, int(account)),
                )
                row = await cur.fetchone()
        user_status = row[0] if row else None

        await message.answer(
            f"✅ Bio аккаунта {country}/{account} изменено на:\n{new_bio}",
            reply_markup=account_actions_keyboard(country, account, user_status),
        )
    except Exception as e:
        # Узнаём статус для кнопки
        pool = dispatcher["db"]
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT user_status
                    FROM users
                    WHERE user_country = %s AND user_number = %s
                    """,
                    (country, int(account)),
                )
                row = await cur.fetchone()
        user_status = row[0] if row else None

        await message.answer(
            f"❌ Не удалось изменить bio: {e}",
            reply_markup=account_actions_keyboard(country, account, user_status),
        )

    await state.clear()


@router.message(AccountStates.change_message)
async def process_change_message(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    """
    Обработка ввода пользовательского сообщения для выбранного аккаунта.
    """
    data = await state.get_data()
    country = data.get("country")
    account = data.get("account")

    new_message = (message.text or "").strip()
    if not new_message:
        await message.answer("Сообщение не может быть пустым. Введите текст ещё раз.")
        return

    # Обновляем user_message в БД
    pool = dispatcher["db"]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE users
                SET user_message = %s
                WHERE user_country = %s AND user_number = %s
                """,
                (new_message, country, int(account)),
            )

    # Узнаём статус для кнопки
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT user_status
                FROM users
                WHERE user_country = %s AND user_number = %s
                """,
                (country, int(account)),
            )
            row = await cur.fetchone()
    user_status = row[0] if row else None

    await message.answer(
        f"✅ Сообщение для аккаунта {country}/{account} сохранено.",
        reply_markup=account_actions_keyboard(country, account, user_status),
    )

    await state.clear()


@router.callback_query(F.data == "enable_all")
async def enable_all_handler(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Вкл/Выкл всех аккаунтов:
    - если все выключены -> включаем (user_status = 'on') и запускаем воркеры
    - если есть включённые -> выключаем всех (user_status = 'off')
    """
    from accounts.worker import process_account  # локальный импорт, чтобы избежать циклов

    pool = dispatcher["db"]
    clients = dispatcher["clients"]
    file_lock = dispatcher["file_lock"]
    client_tasks = dispatcher.get("client_tasks", {})

    # Определяем текущее состояние
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM users")
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

            await cur.execute("SELECT COUNT(*) FROM users WHERE user_status = 'on'")
            on_row = await cur.fetchone()
            on_count = on_row[0] if on_row else 0

    # Если все выключены или вообще нет записей -> включаем
    if total > 0 and on_count == 0:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET user_status = 'on'")

        # Запускаем воркеры параллельно (если ещё не запущены)
        for client in clients:
            key = client.session.filename
            task = client_tasks.get(key)
            if task is None or task.done():
                client_tasks[key] = asyncio.create_task(
                    process_account(client, pool, file_lock)
                )
    else:
        # Иначе выключаем всех
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE users SET user_status = 'off'")

    # Перерисовываем меню стран с обновлённым статусом и эмодзи
    await show_countries(callback, dispatcher)


@router.callback_query(F.data.startswith("enable_country:"))
async def enable_country_toggle(callback: CallbackQuery, dispatcher: Dispatcher) -> None:
    """
    Вкл/Выкл аккаунты конкретной страны:
    - если все аккаунты страны off -> включаем только их и запускаем воркеры
    - если есть включённые -> выключаем все аккаунты этой страны
    """
    from accounts.worker import process_account  # локальный импорт, чтобы избежать циклов

    _, country = callback.data.split(":", 1)

    pool = dispatcher["db"]
    clients = dispatcher["clients"]
    file_lock = dispatcher["file_lock"]
    client_tasks = dispatcher.get("client_tasks", {})

    # Определяем текущее состояние для страны
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM users WHERE user_country = %s",
                (country,),
            )
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

            await cur.execute(
                "SELECT COUNT(*) FROM users WHERE user_country = %s AND user_status = 'on'",
                (country,),
            )
            on_row = await cur.fetchone()
            on_count = on_row[0] if on_row else 0

    # Если в стране есть аккаунты и все off -> включаем только их
    if total > 0 and on_count == 0:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET user_status = 'on' WHERE user_country = %s",
                    (country,),
                )

        # Запускаем воркеры только для клиентов этой страны (если ещё не запущены)
        for client in clients:
            session_path = client.session.filename
            acc_country = os.path.basename(os.path.dirname(os.path.dirname(session_path)))
            if acc_country != country:
                continue

            key = client.session.filename
            task = client_tasks.get(key)
            if task is None or task.done():
                client_tasks[key] = asyncio.create_task(
                    process_account(client, pool, file_lock)
                )

    else:
        # Иначе выключаем все аккаунты этой страны
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE users SET user_status = 'off' WHERE user_country = %s",
                    (country,),
                )

    # Перерисовываем меню аккаунтов в стране
    callback.data = f"country:{country}"
    await show_accounts(callback, dispatcher)


@router.callback_query(F.data.startswith("enable_country:"))
async def enable_country_stub(callback: CallbackQuery) -> None:
    await callback.answer("Включение страны пока не реализовано", show_alert=True)

