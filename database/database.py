import pymongo, os
from config import DB_URI, DB_NAME

#-------------------------------------
bot_loop = bot.loop
bot_name = bot.me.username

dbclient = pymongo.MongoClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

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

async def present_user(user_id : int):
    found = user_data.find_one({'_id': user_id})
    return bool(found)

async def add_user(user_id: int):
    user_data.insert_one({'_id': user_id})
    return

async def full_userbase():
    user_docs = user_data.find()
    user_ids = []
    for doc in user_docs:
        user_ids.append(doc['_id'])
        
    return user_ids

async def del_user(user_id: int):
    user_data.delete_one({'_id': user_id})
    return
