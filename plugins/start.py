import os
import asyncio
import base64
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
import random
from bot import Bot
from config import DB_URI, DB_NAME, ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT
from helper_func import subscribed, encode, decode, get_messages
from database.database import add_user, del_user, full_userbase, present_user
import logging
from datetime import datetime, timedelta
import secrets
import pymongo
from motor import motor_asyncio
import http.client
import json
import aiohttp

SHORT_URL = "api.shareus.io"
SHORT_API = "PUIAQBIFrydvLhIzAOeGV8yZppu2"
# Configure your logger as per your logging settings
logger = logging.getLogger(__name__)

async def get_shortlink(link, short_url, short_api):
    url = f'{short_url}/api'
    params = {'api': short_api, 'url': link}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                
                if data["status"] == "success":
                    return data['shortenedUrl']
                else:
                    logger.error(f"Error: {data.get('message', 'Unknown error')}")
                    return link
    except aiohttp.ClientError as e:
        logger.error(f"AIOHTTP Client Error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")

    return link


# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 60

async def send_message(client, chat_id, text):
    await client.send_chat_action(chat_id, "typing")
    await asyncio.sleep(1)  # Simulate typing (optional)
    await client.send_message(chat_id, text)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def get_unused_token():
    unused_token = await tokens_collection.find_one({"user_id": {"$exists": False}})
    return unused_token

async def user_has_valid_token(user_id):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        expiration_time = stored_token_info.get("expiration_time")
        return expiration_time and expiration_time > datetime.now()
    return False

# Use TOKEN_EXPIRATION_PERIOD
async def generate_24h_token(user_id):
    token = secrets.token_hex(16)
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": token, "expiration_time": expiration_time}},
        upsert=True
    )
    # If you need the encoded token for some reason, return it
    encoded_token = base64.b64encode(token.encode()).decode()
    return encoded_token
    
async def reset_token_verification(user_id):
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

async def get_stored_token(user_id):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None

async def generate_and_send_new_token(client: Client, message: Message):
    user_id = message.from_user.id
    token = await generate_24h_token(user_id)
    await message.reply(f"Your new token: {token}")

async def generate_and_send_new_token_with_link(client: Client, message: Message):
    user_id = message.from_user.id
    stored_token = await get_stored_token(user_id)
    
    if not stored_token:
        # Generate a new 24h token for the user
        token = secrets.token_hex(16)
        expiration_time = datetime.now() + timedelta(hours=24)
        await tokens_collection.update_one(
            {"user_id": user_id},
            {"$set": {"token": token, "expiration_time": expiration_time}},
            upsert=True
        )
        stored_token = token
    
    token_link = f"https://t.me/{client.username}?token={stored_token}"
    short_link = await get_shortlink(token_link)
    
    await send_message(client, message.from_user.id,
                       f"Your previous token has expired. Here is your new 24h token link: {short_link}. "
                       f"Use /check to verify.")

@Bot.on_message(filters.private & filters.command('deleteall') & filters.user(ADMINS))
async def delete_all_data(client: Bot, message: Message):
    await user_data.drop()  # Drops the entire collection holding user data
    await tokens_collection.delete_many({})  # Deletes all tokens
    await message.reply("All user data and tokens have been deleted from the database.")


@Bot.on_message(filters.command("check"))
async def check_command(client: Client, message: Message):
    user_id = message.from_user.id

    if await present_user(user_id):
        if await user_has_valid_token(user_id):
            stored_token_info = await tokens_collection.find_one({"user_id": user_id})
            stored_token = stored_token_info["token"]
            expiration_time = stored_token_info["expiration_time"]
            remaining_time = expiration_time - datetime.now()

            if remaining_time.total_seconds() > 0:
                user_info = await client.get_users(user_id)
                first_name = user_info.first_name
                last_name = user_info.last_name
                username = user_info.username
                mention = user_info.mention
                user_id = user_info.id

                await message.reply_text(
                    f"Token is valid for {int(remaining_time.total_seconds() / 3600)} hours and "
                    f"{int((remaining_time.total_seconds() % 3600) / 60)} minutes.\n\n"
                    f"User Details:\n"
                    f"First Name: {first_name}\n"
                    f"Last Name: {last_name}\n"
                    f"Username: {username}\n"
                    f"Mention: {mention}\n"
                    f"User ID: {user_id}"
                )
            else:
                await generate_and_send_new_token_with_link(client, message)
        else:
            await message.reply("Token is not valid. Please generate a new token.")
    else:
        await message.reply("You are not registered. Please use /start to register.")
        
# ... (other existing code)
@Bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # Check if the user has a valid token
    if await user_has_valid_token(user_id):
        await message.reply("You have a valid token. Use /check to verify.")
        # Add the user to the database if not present
        if not await present_user(user_id):
            try:
                await add_user(user_id)
            except:
                pass

        # Process the command based on the message content
        text = message.text
        if len(text) > 7:
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
                    ids = range(start, end + 1)
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
                    caption = CUSTOM_CAPTION.format(
                        previouscaption="" if not msg.caption else msg.caption.html,
                        filename=msg.document.file_name
                    )
                else:
                    caption = "" if not msg.caption else msg.caption.html

                if DISABLE_CHANNEL_BUTTON:
                    reply_markup = msg.reply_markup
                else:
                    reply_markup = None

                try:
                    await msg.copy(
                        chat_id=message.from_user.id,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                        protect_content=PROTECT_CONTENT
                    )
                    await asyncio.sleep(0.5)
                except FloodWait as e:
                    await asyncio.sleep(e.x)
                    await msg.copy(
                        chat_id=message.from_user.id,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                        protect_content=PROTECT_CONTENT
                    )
                except:
                    pass
            return
        else:
            # Reply with the default message when the command doesn't match the expected format
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("😊 About Me", callback_data="about"),
                        InlineKeyboardButton("🔒 unlock", url="https://shrs.link/FUmxXe")
                    ],
                    [
                        InlineKeyboardButton("Stop Process", callback_data="about")
                    ]
                ]
            )
            await message.reply_text(
                text=START_MSG.format(
                    first=message.from_user.first_name,
                    last=message.from_user.last_name,
                    username=None if not message.from_user.username else '@' + message.from_user.username,
                    mention=message.from_user.mention,
                    id=message.from_user.id
                ),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                quote=True
            )
            return
    else:
        # Handle cases where the user doesn't have a valid token
        await generate_and_send_new_token_with_link(client, message)
   
# ... (rest of your existing code)


# ... (rest of your existing code)



        
    
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
