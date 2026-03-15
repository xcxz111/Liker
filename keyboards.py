from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Аккаунты", callback_data="accounts_menu")],
            [InlineKeyboardButton(text="Статистика", callback_data="stats")],
        ]
    )


def countries_keyboard(country_counts: dict[str, tuple[int, int]], total_all: int, enabled_all: int) -> InlineKeyboardMarkup:
    rows = []
    for country, (total, on_count) in sorted(country_counts.items()):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{country} - {on_count}/{total}",
                    callback_data=f"country:{country}",
                )
            ]
        )

    # Нижний ряд с управлением
    if enabled_all == 0:
        toggle_emoji = "🔴"  # все выключены
    elif enabled_all == total_all:
        toggle_emoji = "🟢"  # все включены
    else:
        toggle_emoji = "🔵"  # включены частично
    rows.append(
        [
            InlineKeyboardButton(text=f"Вкл/Выкл {toggle_emoji}", callback_data="enable_all"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data="back_main"),
            InlineKeyboardButton(text="Главная", callback_data="main_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def accounts_keyboard(
    country: str,
    accounts: list[str],
    total: int,
    enabled: int,
    statuses: dict[str, str],
) -> InlineKeyboardMarkup:
    rows = []
    for acc in sorted(accounts):
        status = statuses.get(acc)
        if status == "on":
            acc_emoji = "🟢"
        elif status == "error" or status is None:
            acc_emoji = "❌"
        else:
            acc_emoji = "🔴"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{acc} {acc_emoji}",
                    callback_data=f"acc:{country}:{acc}",
                )
            ]
        )

    # Определяем эмодзи для состояния страны
    if enabled == 0:
        emoji = "🔴"
    elif enabled == total:
        emoji = "🟢"
    else:
        emoji = "🔵"

    rows.append(
        [
            InlineKeyboardButton(
                text=f"Вкл/Выкл страну {emoji}",
                callback_data=f"enable_country:{country}",
            ),
        ]
    )

    # Массовые операции по стране (ниже переключателя страны)
    rows.append(
        [
            InlineKeyboardButton(
                text="Изменить имена всем ✏️",
                callback_data=f"bulk_name:{country}",
            ),
            InlineKeyboardButton(
                text="Изменить bio всем 📝",
                callback_data=f"bulk_bio:{country}",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Изменить фото всем 🖼",
                callback_data=f"bulk_photo:{country}",
            ),
            InlineKeyboardButton(
                text="Изменить сообщения всем 💬",
                callback_data=f"bulk_message:{country}",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data="back_countries"),
            InlineKeyboardButton(text="Главная", callback_data="main_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def account_actions_keyboard(country: str, account: str, status: str = None) -> InlineKeyboardMarkup:
    """
    Клавиатура действий для конкретного аккаунта.
    """
    if status == "on":
        toggle_emoji = "🟢"
    elif status == "error":
        toggle_emoji = "❌"
    else:
        toggle_emoji = "🔴"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Изменить имя",
                    callback_data=f"acc_action:name:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить bio",
                    callback_data=f"acc_action:bio:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить фото",
                    callback_data=f"acc_action:photo:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Изменить сообщение",
                    callback_data=f"acc_action:message:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Вкл/Выкл аккаунт {toggle_emoji}",
                    callback_data=f"acc_toggle:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Удалить аккаунт",
                    callback_data=f"acc_delete:{country}:{account}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"back_accounts:{country}",
                ),
                InlineKeyboardButton(
                    text="Главная",
                    callback_data="main_menu",
                ),
            ],
        ]
    )


def stats_keyboard(chats_total: int, channels_total: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для раздела статистики.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Чаты - {chats_total}",
                    callback_data="stats_chats",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Каналы - {channels_total}",
                    callback_data="stats_channels",
                )
            ],
            [
                InlineKeyboardButton(text="Назад", callback_data="back_main"),
                InlineKeyboardButton(text="Главная", callback_data="main_menu"),
            ],
        ]
    )


def stats_chats_keyboard(lang_counts: dict[str, int]) -> InlineKeyboardMarkup:
    """
    Клавиатура для статистики по чатам по языкам.
    """
    rows = []
    for lang, count in sorted(lang_counts.items()):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{lang} - {count}",
                    callback_data=f"stats_chats_lang:{lang}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data="stats"),
            InlineKeyboardButton(text="Главная", callback_data="main_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def stats_channels_keyboard(lang_counts: dict[str, int]) -> InlineKeyboardMarkup:
    """
    Клавиатура для статистики по каналам по языкам (только с включёнными комментариями).
    """
    rows = []
    for lang, count in sorted(lang_counts.items()):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{lang} - {count}",
                    callback_data=f"stats_channels_lang:{lang}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(text="Назад", callback_data="stats"),
            InlineKeyboardButton(text="Главная", callback_data="main_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)





