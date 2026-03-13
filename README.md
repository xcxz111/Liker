# liker_bot

Telegram-бот на Python, который управляет фермой аккаунтов и чатами для лайков (реакций).

## Установка

1. **Клонируйте или откройте проект** в этой папке `liker_bot`.
2. **Создайте и активируйте виртуальное окружение (рекомендуется)**:

```bash
cd liker_bot
python3 -m venv .venv
source .venv/bin/activate  # для macOS / Linux
# или
.venv\Scripts\activate     # для Windows (PowerShell/cmd)
```

3. **Установите зависимости**:

```bash
pip install -r requirements.txt
```

4. **Настройте базу данных MySQL**

Создайте новую БД (например, `liker_bot`) и пользователя с доступом к ней.

5. **Создайте файл окружения**:

Скопируйте `.env.example` в `.env`:

```bash
cp .env.example .env
```

Откройте `.env` и заполните переменные (см. пример).

## Настройка

В файле `.env` должны быть переменные (см. `.env.example`):

- `BOT_TOKEN` — токен Telegram-бота;
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` — доступ к MySQL;
- `COUNTRY_FOLDER` — путь к папке с аккаунтами (по умолчанию `accounts`);
- `ADMIN_ID` — твой Telegram ID (`288657881`);
- `API_ID`, `API_HASH` — данные для Telethon‑клиентов аккаунтов.

## Запуск

Из корня проекта (`liker_bot`):

```bash
python main.py
```

Бот запустится в режиме поллинга.

## Что уже делает каркас

- Отвечает на команду `/start` (только от администратора).
- Подключается к MySQL и создаёт две таблицы:
  - `users` — наши аккаунты;
  - `chats` — чаты, где ставим реакции.

Дальше поверх этого каркаса будем добавлять:

- подключение аккаунтов из `accounts/COUNTRY/NUMBER/*.session`;
- логику входа в чаты, определения языка, выбора сообщений и постановки реакций;
- учёт статистики в полях `like_count`, `last_liked_message_id`, `last_like_at`, `last_account_id` и т.д.

