import os
import asyncio
import base64
import logging
import secrets
from datetime import datetime, timedelta
import aiohttp
from uuid import uuid4
import requests
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from motor import motor_asyncio
from bot import Bot
from config import (
    DB_URI, DB_NAME, ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT
)
from helper_func import subscribed, encode, decode, get_messages
from database.database import add_user, del_user, full_userbase, present_user

# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']
SHORT_URL = "vnshortener.com"
SHORT_API = "d20fd8cb82117442858d7f2acdb75648e865d2f9"
# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 86

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


def get_readable_time(seconds):
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result

@Bot.on_message(filters.command('startt'))
async def start(client: Client, message: Message):
    if len(message.command) > 1 and len(message.command[1]) == 36:
        userid = message.from_user.id
        input_token = message.command[1]
        if DATABASE_URL:
            stored_token = await DbManager().get_user_token(userid)
            if stored_token is None:
                return await sendMessage(message, 'This token is not associated with your account.\n\nPlease generate your own token.')
            if input_token != stored_token:
                return await sendMessage(message, 'Invalid token.\n\nPlease generate a new one.')
        if userid not in user_data:
            return await sendMessage(message, 'This token is not yours!\n\nKindly generate your own.')
        data = user_data[userid]
        if 'token' not in data or data['token'] != input_token:
            return await sendMessage(message, 'Token already used!\n\nKindly generate a new one.')
        token = str(uuid4())
        ttime = time()
        data['token'] = token
        data['time'] = ttime
        user_data[userid].update(data)
        if DATABASE_URL:
            await DbManager().update_user_tdata(userid, token, ttime)
        msg = 'Token refreshed successfully!\n\n'
        msg += f'Validity: {get_readable_time(int(TOKEN_EXPIRATION_PERIOD))}'
        return await sendMessage(message, msg)
    elif config_dict['DM_MODE'] and message.chat.type != message.chat.type.SUPERGROUP:
        start_string = 'Bot Started.\n' \
                       'Now I will send all of your stuffs here.\n' \
                       'Use me at: @ultroidxTeam'
    elif not config_dict['DM_MODE'] and message.chat.type != message.chat.type.SUPERGROUP:
        start_string = 'Sorry, you cannot use me here!\n' \
                       'Join: @ultroidxTeam to use me.\n' \
                       'Thank You'
    else:
        tag = message.from_user.mention
        start_string = 'Start me in DM, not in the group.\n' \
                       f'cc: {tag}'
    await sendMessage(message, start_string)

@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    id = message.from_user.id
    if not await present_user(id):
        try:
            await add_user(id)
        except:
            pass
    text = message.text
    if len(text)>7:
        try:
            base64_string = text.split(" ", 1)[1]
        except:
            return
        string = await decode(base64_string)
        argument = string.split("-")
        if len(argument) == 3:
            try:
                start = int(int(argument[1]) / abs(client.db_channel.id))
                end = int(int(argument[2]) / abs(client.db_channel.id))
            except:
                return
            if start <= end:
                ids = range(start,end+1)
            else:
                ids = []
                i = start
                while True:
                    ids.append(i)
                    i -= 1
                    if i < end:
                        break
        elif len(argument) == 2:
            try:
                ids = [int(int(argument[1]) / abs(client.db_channel.id))]
            except:
                return
        temp_msg = await message.reply("Please wait...")
        try:
            messages = await get_messages(client, ids)
        except:
            await message.reply_text("Something went wrong..!")
            return
        await temp_msg.delete()

        for msg in messages:

            if bool(CUSTOM_CAPTION) & bool(msg.document):
                caption = CUSTOM_CAPTION.format(previouscaption = "" if not msg.caption else msg.caption.html, filename = msg.document.file_name)
            else:
                caption = "" if not msg.caption else msg.caption.html

            if DISABLE_CHANNEL_BUTTON:
                reply_markup = msg.reply_markup
            else:
                reply_markup = None

            try:
                await msg.copy(chat_id=message.from_user.id, caption = caption, parse_mode = ParseMode.HTML, reply_markup = reply_markup, protect_content=PROTECT_CONTENT)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await msg.copy(chat_id=message.from_user.id, caption = caption, parse_mode = ParseMode.HTML, reply_markup = reply_markup, protect_content=PROTECT_CONTENT)
            except:
                pass
        return
    else:
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("😊 About Me", callback_data = "about"),
                    InlineKeyboardButton("🔒 unlock", url="https://shrs.link/FUmxXe")
                ]
            ]
        )
        await message.reply_text(
            text = START_MSG.format(
                first = message.from_user.first_name,
                last = message.from_user.last_name,
                username = None if not message.from_user.username else '@' + message.from_user.username,
                mention = message.from_user.mention,
                id = message.from_user.id
            ),
            reply_markup = reply_markup,
            disable_web_page_preview = True,
            quote = True
        )
        return


#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##

    
    
@Bot.on_message(filters.command('start') & filters.private)
async def not_joined(client: Client, message: Message):
    buttons = [
        [
            InlineKeyboardButton(
                "Join Channel",
                url = client.invitelink)
        ]
    ]
    try:
        buttons.append(
            [
                InlineKeyboardButton(
                    text = 'Try Again',
                    url = f"https://t.me/{client.username}?start={message.command[1]}"
                )
            ]
        )
    except IndexError:
        pass

    await message.reply(
        text = FORCE_MSG.format(
                first = message.from_user.first_name,
                last = message.from_user.last_name,
                username = None if not message.from_user.username else '@' + message.from_user.username,
                mention = message.from_user.mention,
                id = message.from_user.id
            ),
        reply_markup = InlineKeyboardMarkup(buttons),
        quote = True,
        disable_web_page_preview = True
    )

@Bot.on_message(filters.command('users') & filters.private & filters.user(ADMINS))
async def get_users(client: Bot, message: Message):
    msg = await client.send_message(chat_id=message.chat.id, text=WAIT_MSG)
    users = await full_userbase()
    await msg.edit(f"{len(users)} users are using this bot")

@Bot.on_message(filters.private & filters.command('broadcast') & filters.user(ADMINS))
async def send_text(client: Bot, message: Message):
    if message.reply_to_message:
        query = await full_userbase()
        broadcast_msg = message.reply_to_message
        total = 0
        successful = 0
        blocked = 0
        deleted = 0
        unsuccessful = 0
        
        pls_wait = await message.reply("<i>Broadcasting Message.. This will Take Some Time</i>")
        for chat_id in query:
            try:
                await broadcast_msg.copy(chat_id)
                successful += 1
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await broadcast_msg.copy(chat_id)
                successful += 1
            except UserIsBlocked:
                await del_user(chat_id)
                blocked += 1
            except InputUserDeactivated:
                await del_user(chat_id)
                deleted += 1
            except:
                unsuccessful += 1
                pass
            total += 1
        
        status = f"""<b><u>Broadcast Completed</u>

Total Users: <code>{total}</code>
Successful: <code>{successful}</code>
Blocked Users: <code>{blocked}</code>
Deleted Accounts: <code>{deleted}</code>
Unsuccessful: <code>{unsuccessful}</code></b>"""
        
        return await pls_wait.edit(status)

    else:
        msg = await message.reply(REPLY_ERROR)
        await asyncio.sleep(8)
        await msg.delete()                
        
