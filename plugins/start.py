import os
import asyncio
import base64
import logging
import secrets
from datetime import datetime, timedelta

import aiohttp
import requests
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from motor import motor_asyncio

from bot import Bot
from config import (
    DB_URI, DB_NAME, ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT
)
from helper_func import subscribed, encode, decode, get_messages
from database.database import add_user, del_user, full_userbase, present_user

SHORT_URL = "api.shareus.io"
SHORT_API = "PUIAQBIFrydvLhIzAOeGV8yZppu2"
TOKEN_EXPIRATION_PERIOD = 100

logger = logging.getLogger(__name__)

async def shorten_url_with_shareusio(url, short_url, short_api):
    api_endpoint = f'http://{short_url}/api'  # Adding 'http://' as the schema
    params = {'api': short_api, 'url': url}

    try:
        response = requests.get(api_endpoint, params=params)
        if response.status_code == 200:
            data = response.json()
            if data["status"] == "success":
                return data.get('shortenedUrl')  # Return shortened URL
            else:
                logger.error(f"Error: {data.get('message', 'Unknown error')}")
        else:
            logger.error(f"Error: Status Code - {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Request Exception: {e}")
    return None  # Return None if any error occurs

    
async def generate_24h_token(user_id, tokens_collection):
    token = secrets.token_hex(8)
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": token, "expiration_time": expiration_time}},
        upsert=True
    )
   
async def generate_and_send_new_token_with_link(client: Client, message: Message):
    user_id = message.from_user.id
    stored_token = await get_stored_token(user_id, tokens_collection)
    
    if not stored_token:
        # Inform the user about the missing token and how to obtain it
        await message.reply(client, user_id, "You don't have a valid token. Please obtain a token first to proceed.")
        return  # Exit the function without further processing
    
    base_url = f"https://t.me/{client.username}"
    tokenized_url = f"{base_url}?start=token_{stored_token}"
    
    short_link = await shorten_url_with_shareusio(tokenized_url, SHORT_URL, SHORT_API)
    
    if short_link:
        # Create an InlineKeyboardMarkup with a button leading to the shortened link
        button = InlineKeyboardButton("Open Link", url=short_link)
        keyboard = InlineKeyboardMarkup([[button]])
        
        # Send the message with the shortened link and the button
        await message.reply(text="Here is your shortened link:", reply_markup=keyboard, disable_notification=True)
    else:
        await message.reply(client, user_id, "There was an error generating the shortened link. Please try again later.")
        
async def encode(string):
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = (base64_bytes.decode("ascii")).strip("=")
    return base64_string

async def decode(base64_string):
    base64_string = base64_string.strip("=") # links generated before this commit will be having = sign, hence striping them to handle padding errors.
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes) 
    string = string_bytes.decode("ascii")
    return string

# Other parts of your code remain unchanged
# Ensure you integrate these adjustments into your existing codebase and test thoroughly.

# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 100


async def get_unused_token():
    unused_token = await tokens_collection.find_one({"user_id": {"$exists": False}})
    return unused_token

async def user_has_valid_token(user_id):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        expiration_time = stored_token_info.get("expiration_time")
        return expiration_time and expiration_time > datetime.now()
    return False
    
async def reset_token_verification(user_id):
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

async def get_stored_token(user_id, tokens_collection):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None


async def generate_and_send_new_token(client: Client, message: Message):
    user_id = message.from_user.id
    token = await generate_24h_token(user_id)
    await message.reply(f"Your new token: {token}")


@Bot.on_message(filters.command('deleteall'))
async def delete_all_data(client: Client, message: Message):
    try:
        await user_data.drop()  # Drops the entire collection holding user data
        await tokens_collection.delete_many({})  # Deletes all tokens
        await message.reply("All user data and tokens have been deleted from the database.")
    except Exception as e:
        await message.reply(f"An error occurred: {str(e)}")
        

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
