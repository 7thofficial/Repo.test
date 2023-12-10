from os import environ
from aiofiles import open as aiopen
from aiofiles.os import makedirs
from aiofiles.os import path as aiopath
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
from time import time

from bot import Bot
from config import (
    DB_URI, DB_NAME, user_data
)


class DbManager:
    def __init__(self):
        self.__err = False
        self.__db = None
        self.__conn = None
        self.__connect()

    def __connect(self):
        try:
            self.__conn = AsyncIOMotorClient(DB_URI)
            self.__db = self.__conn.z
        except PyMongoError as e:
            LOGGER.error(f"Error in DB connection: {e}")
            self.__err = True

    async def update_config(self, dict_):
        if self.__err:
            return
        await self.__db.settings.config.update_one({'_id': bot_id}, {'$set': dict_}, upsert=True)
        self.__conn.close
      
    async def update_user_tdata(self, user_id, token, time):
        if self.__err:
            return
        await self.__db.access_token.update_one({'_id': user_id}, {'$set': {'token': token, 'time': time}}, upsert=True)
        self.__conn.close

    async def update_user_token(self, user_id, token):
        if self.__err:
            return
        await self.__db.access_token.update_one({'_id': user_id}, {'$set': {'token': token}}, upsert=True)
        self.__conn.close

    async def get_token_expire_time(self, user_id):
        if self.__err:
            return None
        user_data = await self.__db.access_token.find_one({'_id': user_id})
        if user_data:
            return user_data.get('time')
        self.__conn.close
        return None

    async def get_user_token(self, user_id):
        if self.__err:
            return None
        user_data = await self.__db.access_token.find_one({'_id': user_id})
        if user_data:
            return user_data.get('token')
        self.__conn.close
        return None

    async def delete_all_access_tokens(self):
        if self.__err:
            return
        await self.__db.access_token.delete_many({})
        self.__conn.close

if DB_URI:
    bot_loop.run_until_complete(DbManager().db_load())
