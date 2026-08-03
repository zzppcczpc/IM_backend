from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings

client = AsyncIOMotorClient(settings.DATABASE_URL)
manage_db = client.xboom
chat_db = client.chat


async def get_database():
    return manage_db


async def get_chat_database():
    return chat_db