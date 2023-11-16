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

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

# Function to generate a token for a user and store it in the database
async def generate_token(user_id):
    token = secrets.token_hex(6)  # Generating a 6-digit hexadecimal token
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)  # Token expiration in 1 day

    # Store the token and its expiration time in the database for the user
    user_data.update_one(
        {"user_id": user_id},
        {"$set": {"token": token, "expiration_time": expiration_time}},
        upsert=True
    )
    return token

async def add_user(user_id):
    user = await user_data.find_one({'_id': user_id})
    if user:
        # Handle the case where the user already exists (possibly update some information)
        # You can add logic here to update user information if needed
        pass
    else:
        # If the user doesn't exist, insert them into the database
        await user_data.insert_one({'_id': user_id})


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

async def generate_and_send_new_token_with_link(client: Client, message: Message):
    user_id = message.from_user.id
    stored_token = await get_stored_token(user_id, tokens_collection)
    
    if not stored_token:
        # Generate a new token and save it
        await generate_token(user_id, tokens_collection)
        # Retrieve the newly generated token
        stored_token = await get_stored_token(user_id, tokens_collection)
        if not stored_token:
            await message.reply_text("There was an error generating a new token. Please try again later.", quote=True)
            return  # Exit the function without further processing

    base64_string = await (f"token_{stored_token}")
    base_url = f"https://t.me/{client.username}"
    tokenized_url = f"{base_url}?start={base64_string}"
    
    short_link = await shorten_url_with_shareusio(tokenized_url, SHORT_URL, SHORT_API)
    
    if short_link:
        await save_base64_string(user_id, base64_string, tokens_collection)
        # Create an InlineKeyboardMarkup with a button leading to the shortened link
        button = InlineKeyboardButton("Open Link", url=short_link)
        keyboard = InlineKeyboardMarkup([[button]])
        
        # Send the message with the shortened link and the button
        await message.reply_text("Here is your shortened link:", reply_markup=keyboard, disable_notification=True)
    else:
        await message.reply_text("There was an error generating the shortened link. Please try again later.", quote=True)

        

#async def is_valid_token(user_id):
#    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
  #  if stored_token_info:
  #      expiration_time = stored_token_info.get("expiration_time")
  #      return expiration_time and expiration_time > datetime.now()
  #  return False

async def is_valid_token(user_id, received_token):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        stored_token = stored_token_info.get("token")
        expiration_time = stored_token_info.get("expiration_time")
        
        if expiration_time and expiration_time > datetime.now():
            # Check if the received token matches the stored token
            if received_token == stored_token:
                print(f"Received Token: {received_token}")
                print(f"Stored Token: {stored_token}")
                print("Token Matched!")
                return True
            else:
                print(f"Received Token: {received_token}")
                print(f"Stored Token: {stored_token}")
                print("Tokens Do Not Match!")
        else:
            print("Token Expired!")
    else:
        print("No Token Found for User!")
    return False

    
    
async def reset_token_verification(user_id):
    # Your logic to reset the token verification process
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

async def get_stored_token(user_id):
    # Your logic to retrieve stored token from MongoDB
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None


@Bot.on_message(filters.command('start'))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    command = message.text.split("_")

    if len(command) == 2 and command[1].startswith("token_"):
        received_token = command[1][6:]
        received_token = await decode(received_token_encoded)  # Decode the received token
        
        if await is_valid_token(user_id, received_token):
            await message.reply("Welcome! Your token is valid. Access granted.")
            await start_process(client, message)
        else:
            print(f"User {user_id} tried with an invalid token: {received_token}")
            await message.reply("Sorry, the token is invalid. Please generate a new one.")
            await message.reply("Please verify your token using /check.")
    else:
        # Generate a new token if the user doesn't have a valid one
        token = await generate_token(user_id)
        print(f"Generated token for user {user_id}: {token}")
        
        base_url = f"https://t.me/{client.username}"
        tokenized_url = f"{base_url}?start=token_{token}"
        
        short_link = await shorten_url_with_shareusio(tokenized_url, SHORT_URL, SHORT_API)
        
        if short_link:
            await message.reply(f"Welcome! Your token has been generated. Use this link to verify: {short_link}")
        else:
            await message.reply("There was an error generating the verification link. Please try again later.")
            

async def start_process(client: Client, message: Message):
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
        
