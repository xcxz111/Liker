import os

import aiomysql
from dotenv import load_dotenv


load_dotenv()


async def create_pool():
    pool = await aiomysql.create_pool(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        db=os.getenv("DB_NAME", "liker_bot"),
        autocommit=True,
    )
    return pool

