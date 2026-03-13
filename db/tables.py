async def create_tables(pool):
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # =========================
            # TABLE: users
            # =========================
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_number BIGINT,
                    user_id BIGINT UNIQUE NOT NULL,
                    user_name VARCHAR(255),
                    user_bio TEXT,
                    user_message TEXT,
                    user_country VARCHAR(50),
                    user_status VARCHAR(50) DEFAULT 'off',
                    like_count BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # =========================
            # TABLE: chats
            # =========================
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chat_name VARCHAR(255),
                    chat_username VARCHAR(255),
                    chat_link VARCHAR(255),
                    chat_description TEXT,
                    chat_created_at TIMESTAMP NULL,
                    chat_status VARCHAR(50),
                    user_count BIGINT,
                    chat_country VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_liked_message_id BIGINT,
                    last_like_at TIMESTAMP NULL,
                    last_account_id INT,
                    like_count BIGINT DEFAULT 0
                )
                """
            )

            # =========================
            # TABLE: channels
            # =========================
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    channel_name VARCHAR(255),
                    channel_username VARCHAR(255),
                    channel_link VARCHAR(255),
                    channel_description TEXT,
                    channel_created_at TIMESTAMP NULL,
                    channel_status VARCHAR(50),
                    channel_comments TINYINT(1),
                    user_count BIGINT,
                    channel_country VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_liked_post_id BIGINT,
                    last_liked_message_id BIGINT,
                    last_like_at TIMESTAMP NULL,
                    last_account_id INT,
                    like_count BIGINT DEFAULT 0
                )
                """
            )

