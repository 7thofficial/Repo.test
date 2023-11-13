import os
import asyncio
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
import shortzy
import http.client
import json

# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 86

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def get_unused_token():
    # Your logic to get an unused token
    unused_token = await tokens_collection.find_one({"user_id": {"$exists": False}})
    return unused_token

async def user_has_valid_token(user_id):
    # Your logic to check if the user has a valid token
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        expiration_time = stored_token_info.get("expiration_time")
        return expiration_time and expiration_time > datetime.now()
    return False

# Inside the "generate_token" function
async def generate_token(user_id):
    # Your existing logic to generate a unique token for a user
    token = secrets.token_hex(16)
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"token": token, "expiration_time": expiration_time}}, upsert=True)

    # Generate a link with the token
    token_link = f"https://t.me/{client.username}?token={token}"

    # Shorten the token link using shortzy
    short_token_link = await shorten_link(token_link)

    return token, short_token_link

async def shorten_link(link):
    # Shorten the link using shortzy
    conn = http.client.HTTPSConnection("api.shareus.io")
    payload = json.dumps({
        "api_key": "PUIAQBIFrydvLhIzAOeGV8yZppu2",
        "url": link,
        "category": "Entertainment",
        "tags": ["trendinglinks"]
    })
    headers = {
        'Keep-Alive': '',
        'Content-Type': 'application/json'
    }
    conn.request("POST", "/generate_link", payload, headers)
    res = conn.getresponse()
    data = res.read()
    short_link = json.loads(data.decode("utf-8"))["short_link"]
    return short_link

# ... (your existing code)

async def reset_token_verification(user_id):
    # Your logic to reset the token verification process
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

async def get_stored_token(user_id):
    # Your logic to retrieve stored token from MongoDB
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None

# ... (rest of your existing code)

# Inside the "start_command" function
@Bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # Check if the user is already in the database
    if not await present_user(user_id):
        # Generate a new token for the user
        token = await generate_token(user_id)
        await add_user(user_id)
        await message.reply(f"Welcome! Your token is: `{token}` Use /check to verify.")
    else:
        # Check if the user has a valid token
        if await user_has_valid_token(user_id):
            await message.reply("You have a valid token. Use /check to verify.")
        else:
            await message.reply(f"Please provide a token using /token `{token}`.")
    return  # Fix: Remove extra else
    
# Inside the "check_command" function
@Bot.on_message(filters.command("check"))
async def check_command(client: Client, message: Message):
    user_id = message.from_user.id

    # Check if the user is in the database
    if await present_user(user_id):
        # Check if the user has a valid token
        if await user_has_valid_token(user_id):
            stored_token_info = await tokens_collection.find_one({"user_id": user_id})
            expiration_time = stored_token_info.get("expiration_time")
            stored_token = stored_token_info.get("token")

            if expiration_time and expiration_time > datetime.now():
                remaining_time = expiration_time - datetime.now()
                user = message.from_user
                username = f"@{user.username}" if user.username else "not set"
                await message.reply(f"Your token: `{stored_token}` is valid. Use it to access the features.\n\nUser Details:\n- ID: {user.id}\n- First Name: {user.first_name}\n- Last Name: {user.last_name}\n- Username: {username}\n\nToken Expiration Time: {remaining_time}")
            else:
                # Generate a new token for the user
                new_token = await generate_token(user_id)
                await message.reply(f"You don't have a valid token. Your new token: `{new_token}`.\n\nTo connect the new token, use the command:\n`/connect {new_token}`.")
        else:
            # Generate a new token for the user
            new_token = await generate_token(user_id)
            await message.reply(f"You don't have a valid token. Your new token: `{new_token}`.\n\nTo connect the new token, use the command:\n`/connect {new_token}`.")
    else:
        # Generate a new token for the user
        new_token = await generate_token(user_id)
        await add_user(user_id)
        await message.reply(f"You haven't connected yet. Your new token: `{new_token}`.\n\nTo connect the token, use the command:\n`/connect {new_token}`.")
        


@Bot.on_message(filters.command("token"))
async def token_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_token = message.command[1] if len(message.command) > 1 else None

    # Check if the provided token is valid
    if await user_has_valid_token(user_id):
        await message.reply("You have already provided a valid token. Use /check to verify.")
    elif user_token:
        # Check if the provided token is valid
        token_entry = token_collection.find_one({"token": user_token, "user_id": {"$exists": False}})
        if token_entry:
            token_collection.update_one({"_id": token_entry["_id"]}, {"$set": {"user_id": user_id}})
            user_collection.insert_one({"user_id": user_id, "token": user_token})
            await message.reply("Token accepted! Use /check to verify.")
        else:
            await message.reply("Invalid token. Please try again.")
    else:
        await message.reply("Please provide a token using /token {your_token}.")

@Bot.on_callback_query(filters.regex("^stop_process$"))
async def stop_process_callback(client: Client, query: CallbackQuery):
    await query.answer("Token verification process stopped. Use /start to restart.")
    user_id = query.from_user.id
    user_collection.delete_one({"user_id": user_id})

# ... (rest of your existing code)
# Inside the "start_command" function
@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # Check if the user has a valid token
    if not await user_has_valid_token(user_id):
        await message.reply_text("Please provide a valid token using /token {your_token}.")
        return  # Stop the process if the token is not valid

    # Continue with the existing logic if the token is valid
    if not await present_user(user_id):
        try:
            await add_user(user_id)
        except:
            pass

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
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("😊 About Me", callback_data="about"),
                    InlineKeyboardButton("🔒 unlock", url="https://shrs.link/FUmxXe")
                ],
                [
                    InlineKeyboardButton("Stop Process", callback_data="stop_process")
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
