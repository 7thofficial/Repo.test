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

SHORT_URL = "vnshortener.com"
SHORT_API = "d20fd8cb82117442858d7f2acdb75648e865d2f9"
TOKEN_EXPIRATION_PERIOD = 100

logger = logging.getLogger(__name__)
async def generate_new_token():
    # Generate a new token (random string)
    new_token = secrets.token_hex(16)  # Generates a 32-character random string
    
    # Calculate token expiration time (24 hours from now)
    expiration_time = datetime.now() + timedelta(hours=1)
    
    # Store the new token with expiration time in the database
    await tokens_collection.insert_one({
        "token": new_token,
        "expiration_time": expiration_time
    })
    
    return new_token
    
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


# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

# Token expiration prid (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 100


async def get_unused_token():
    unused_token = await tokens_collection.find_one({"user_id": {"$exists": False}})
    return unused_token

    
async def reset_token_verification(user_id):
    await tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

async def get_stored_token(user_id, tokens_collection):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None

async def user_has_valid_token(user_id):
    # Check if the user has a valid token
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        expiration_time = stored_token_info.get("expiration_time")
        return expiration_time and expiration_time > datetime.now()
    return False
# ... (existing code)

# Main code
# Define your existing message handlers, imports, and other code here

# New code snippet to add

@Bot.on_message(filters.command('start') & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    # Extract the provided token from the command
    if len(message.command) > 1:
        provided_token = message.command[1]
    else:
        # No token provided, handle accordingly
        return

    # Retrieve the bot's user token from the database
    bot_user_id = client.bot_user.id  # Get the bot's user ID
    bot_user_token_info = await tokens_collection.find_one({"user_id": bot_user_id})

    if bot_user_token_info:
        bot_user_token = bot_user_token_info["token"]
        if bot_user_token == provided_token:
            # Update the token as verified for the user
            await tokens_collection.update_one({"user_id": user_id, "token": provided_token}, {"$set": {"verified": True}})
            await message.reply_text("Your provided token matches the bot's user token. Token verified.")
        else:
            await message.reply_text("The provided token is invalid.")
    else:
        await message.reply_text("No token found for the bot user.")
        
              
@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    if await user_has_valid_token(user_id):
        # Existing valid token logic
        text = message.text
        if len(text) > 7:
            try:
                base64_string = text.split(" ", 1)[1]
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
            except:
                pass  # Add handling for any specific exceptions here if needed
        else:
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
    else:
        # Generate a new token if none exists
        new_token = await generate_new_token()  # Correct - this properly awaits the coroutine
# Implement your token generation logic here
        
        # Store the new token with expiration time in the database
        expiration_time = datetime.now() + timedelta(hours=TOKEN_EXPIRATION_PERIOD)
        await tokens_collection.insert_one({
            "user_id": user_id,
            "token": new_token,
            "expiration_time": expiration_time,
            "verified": False
        })

        # Create a deep link for the user
        deep_link = f"https://t.me/{client.username}?start={new_token}"

        # Send the deep link as a button to the user
        #reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Your Token", url=deep_link)]])
        #await message.reply_text("Your new token:", reply_markup=reply_markup)
        deep_link = f"https://t.me/{client.username}?start={new_token}"
        await message.reply_text(f"Your new token: {new_token}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Your Token", url=deep_link)]]))
        
#=====================================================================================##

WAIT_MSG = """"<b>Processing ...</b>"""

REPLY_ERROR = """<code>Use this command as a replay to any telegram message with out any spaces.</code>"""

#=====================================================================================##
# Add logic to verify the provided token when the user clicks the link and starts the bot with the provided token
@Bot.on_message(filters.command('start') & filters.private & filters.regex(r'start=(\w+)'))
async def verify_token(client: Client, message):
    user_id = message.from_user.id
    provided_token = message.matches[0].group(1)

    # Check if the provided token matches the stored token for the user
    stored_token = tokens_collection.find_one({"user_id": user_id, "token": provided_token})

    if stored_token:
        # If the tokens match, mark the token as verified in the database
        tokens_collection.update_one({"user_id": user_id, "token": provided_token}, {"$set": {"verified": True}})
        await message.reply_text("Your provided token is valid. You don't need to verify it again.")
    else:
        await message.reply_text("The provided token is invalid.")


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
