
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
    
# 1. Generate and Save Token with Expiry in Database

async def process_matching_token(client: Client, message: Message):
    user_id = message.from_user.id
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    stored_token = stored_token_info.get("token") if stored_token_info else None

    if stored_token:
        provided_token = message.command[1] if len(message.command) > 1 else None

        if provided_token == stored_token:
            # Token matches, proceed with the action
            print("Token matched.")
            await verify_token(user_id, provided_token, True, message)  # Save token match status in the database
            # Your further logic here
        else:
            # Token didn't match, reply and request verification
            new_token = await generate_24h_token(user_id, tokens_collection)
            new_deep_link = create_telegram_deep_link(new_token)
            print("Token mismatch. New token and link generated:", new_token, new_deep_link)

            # Present the deep link with the token as a button for user verification
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("Verify Token", url=new_deep_link)]
            ])
            await message.reply_text("Please verify your token.", reply_markup=reply_markup)
    else:
        # No stored token found, generate a new token and store it
        new_token = await generate_24h_token(user_id, tokens_collection)
        new_deep_link = create_telegram_deep_link(new_token)
        print("No stored token. New token and link generated:", new_token, new_deep_link)

        # Present the deep link with the token as a button for user verification
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Verify Token", url=new_deep_link)]
        ])
        await message.reply_text("Please verify your token.", reply_markup=reply_markup)


async def generate_24h_token(user_id, tokens_collection):
    # Check if the user already has a valid token
    if await user_has_valid_token(user_id):
        stored_token_info = await tokens_collection.find_one({"user_id": user_id})
        return stored_token_info["token"]

    # Generate a token
    token = secrets.token_hex(8)
    expiration_time = datetime.now() + timedelta(TOKEN_EXPIRATION_PERIOD)

    # Save the token and its expiration time to the database
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": token, "expiration_time": expiration_time}},
        upsert=True
    )
    return token

    
# Check and verify the provided token
async def verify_token(user_id, provided_token):
    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        stored_token = stored_token_info.get("token")
        expiration_time = stored_token_info.get("expiration_time")

        if stored_token == provided_token and expiration_time > datetime.now():
            # Token matches and is valid
            return True, "Token is valid"
        else:
            return False, "Token is invalid or expired"
    else:
        return False, "Token not found for user"

# Logic to handle user connection attempt
async def handle_user_connection(user_id, provided_token):
    verified, message = await verify_token(user_id, provided_token)

    if verified:
        # Token is valid, return details to the user or grant access
        return "Token verification successful, granting access"
    else:
        # Token is invalid or expired, prompt the user to try again or take action accordingly
        return f"Token verification failed: {message}"

async def save_token_match_status(user_id, match_status, message):
    # Update the token match status in the database
    await tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token_match": match_status}},
        upsert=True
    )
    
# 2. Create a Telegram Deep Link with the Token
def create_telegram_deep_link(token):
    # Construct a deep link with the token parameter
    deep_link = f"https://t.me/blank_s_bot?start={token}"
    return deep_link
    
@Bot.on_message(filters.command('start') & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    # Simulate a user connection attempt with the provided token

    # Extract token from the deep link
    provided_token = message.command[1] if len(message.command) > 1 else None

    stored_token_info = await tokens_collection.find_one({"user_id": user_id})
    stored_token = stored_token_info.get("token") if stored_token_info else None

    if provided_token == stored_token:
        # Token matches, proceed with the action
        print("Token matched.")
        # Your further logic here
        await process_matching_token(client, message)
    else:
        # Token didn't match, generate a new token and deep link
        new_token = await generate_24h_token(user_id, tokens_collection)
        new_deep_link = create_telegram_deep_link(new_token)
        print("Token mismatch. New token and link generated:", new_token, new_deep_link)
        provided_token = "user_provided_token"
        verification_result = await handle_user_connection(user_id, provided_token)
        print(verification_result)
        # Present the deep link with the token as a button for user verification
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Verify Token", url=new_deep_link)]
        ])
        await message.reply_text("Please verify your token.", reply_markup=reply_markup)

# ... (other functions and imports)
# ... (other functions and imports)

    # You can use 'message' here as needed
    id = message.from_user.id
    if not await present_user(id):
        try:
            await add_user(id)
        except:
            pass
    # ... (other logic)

    text = message.text
    if len(text) > 7:
        try:
            base64_string = text.split(" ", 1)[1]
        except:
            return
        # ... (Rest of your code for handling the token logic)
    else:
        # Regular start command behavior when tokens match
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
