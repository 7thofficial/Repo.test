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

    
async def encode_token(token):
    # Encode the token to base64 before storing in the database
    encoded_token = await encode(token)
    return encoded_token

# When generating a token, encode it and save the encoded token
async def generate_24h_token(user_id, tokens_collection):
    token = secrets.token_hex(8)
    encoded_token = await encode_token(token)
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": encoded_token, "expiration_time": expiration_time}},
        upsert=True
    )
   
async def generate_and_send_new_token_with_link(client: Client, message: Message):
    user_id = message.from_user.id
    stored_token = await get_stored_token(user_id, tokens_collection)
    
    if not stored_token:
        # Generate a new token and save it
        await generate_24h_token(user_id, tokens_collection)
        # Retrieve the newly generated token
        stored_token = await get_stored_token(user_id, tokens_collection)
        if not stored_token:
            await message.reply_text("There was an error generating a new token. Please try again later.", quote=True)
            return  # Exit the function without further processing

    base64_string = await encode(f"token_{stored_token}")
    base_url = f"https://t.me/{client.username}"
    tokenized_url = f"{base_url}?start={base64_string}"
    
    short_link = await shorten_url_with_shareusio(tokenized_url, SHORT_URL, SHORT_API)
    
    if short_link:
        await save_base64_string(user_id, base64_string, tokens_collection)
        # Rest 
        # Create an InlineKeyboardMarkup with a button leading to the shortened link
        button = InlineKeyboardButton("Open Link", url=short_link)
        keyboard = InlineKeyboardMarkup([[button]])
        
        # Send the message with the shortened link and the button
        await message.reply_text("Here is your shortened link:", reply_markup=keyboard, disable_notification=True)
    else:
        await message.reply_text("There was an error generating the shortened link. Please try again later.", quote=True)


# Inside your code, add the following function to save the base64_string:

async def save_base64_string(user_id, base64_string, tokens_collection):
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"base64_string": base64_string}},
        upsert=True
    )

async def get_stored_base64_string(user_id, tokens_collection):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["base64_string"] if stored_token_info else None
    
        
# When verifying the provided token
async def verify_token_from_url(user_id, provided_base64_string):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        stored_encoded_token = stored_token_info["token"]
        decoded_stored_token = await decode(stored_encoded_token)  # Decoding the stored token
        decoded_provided_token = await decode(provided_base64_string)  # Decoding the provided base64 string
        if decoded_stored_token == decoded_provided_token:
            return True
    return False
# This function will handle the opening of the short link

@Bot.on_inline_query()
async def open_short_link(client, update):
    query = update.inline_query.query
    token = query.split("_", 1)[-1]  # Extracting the token part from the query
    user_id = update.inline_query.from_user.id

    # Assuming the token is part of the query and extracted as 'token'
    is_valid_token = await verify_token_from_url(user_id, token)

    if is_valid_token:
        await update.inline_query.answer([
            InlineQueryResultArticle(
                title="Token verified! Proceed with the desired action.",
                input_message_content=InputTextMessageContent(
                    message_text="Token verified! Proceed with the desired action."
                )
            )
        ])
    else:
        await update.inline_query.answer([
            InlineQueryResultArticle(
                title="Invalid token! Access denied.",
                input_message_content=InputTextMessageContent(
                    message_text="Invalid token! Access denied."
                )
            )
        ])


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
        


@Bot.on_message(filters.command("start"))
@Bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    stored_base64_string = await get_stored_base64_string(user_id, tokens_collection)
    base64_decoded = None

    if len(message.text.split()) > 1:
        base64_command = message.text.split()[1]
        base64_decoded = await decode(base64_command)

    if base64_decoded == stored_base64_string:
        is_valid_token = await verify_token_from_url(user_id, stored_base64_string)

        if is_valid_token:
            # Valid token provided by the user, proceed with the action
            await message.reply_text("Valid token! Proceeding with the action.")
            # Your further logic here
        else:
            # Invalid token provided by the user
            await message.reply_text("Invalid token! Access denied.")
    else:
        # Didn't match; continue with the tokenized URL generation and sending
        await generate_and_send_new_token_with_link(client, message)

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
                string = await decode(base64_string)
                argument = string.split("-")

                # Rest of your logic for message processing...
                # ...
            except:
                pass
        else:
            # Reply with the default message when the command doesn't match the expected format
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("😊 About Me", callback_data="about"),
                        InlineKeyboardButton("🔒 unlock", url="https://shrs.link/FUmxXe")
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
