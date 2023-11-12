import os
import asyncio
from pyrogram import Client, filters, __version__
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
import random
from bot import Bot
from config import ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, DISABLE_CHANNEL_BUTTON, PROTECT_CONTENT
from helper_func import subscribed, encode, decode, get_messages
from database.database import add_user, del_user, full_userbase, present_user
import logging
import asyncio
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from pymongo import MongoClient
from datetime import datetime, timedelta
import secrets

# Set your MongoDB connection URL
MONGODB_URL = "mongodb+srv://Cluster0:Cluster0@cluster0.c07xkuf.mongodb.net/?retryWrites=true&w=majority"

# Connect to MongoDB
client = MongoClient(MONGODB_URL)
db = client["Cluster0"]
tokens_collection = db["tokens"]

# Set your API ID and API Hash
API_ID = "22046181"
API_HASH = "54a82e965ae136785450fc8c2beaaede"

# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 86400

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Define the start command to generate or verify a token
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_token = get_stored_token(user_id)

    if user_token:
        # Check if the token is expired
        if is_token_expired(user_id):
            # Token expired, generate a new one for verification
            new_token = generate_token(user_id)
            update.message.reply_text(f"Your previous token has expired. Your new token is: {new_token}")
        else:
            update.message.reply_text(f"You have a valid token: {user_token}. Use /check to verify.")
    else:
        # No token found, generate a new one for verification
        new_token = generate_token(user_id)
        update.message.reply_text(f"Welcome! Your token for verification is: {new_token}")

# Define a command to check user's token
def check(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_token = context.args[0] if context.args else None

    # Check if the provided token is valid
    if is_valid_token(user_id, user_token):
        update.message.reply_text("Token is valid! Verification successful.")
        reset_token_verification(user_id)
    else:
        update.message.reply_text("Token is invalid. Please check and try again.")

# Function to generate a unique token for a user
def generate_token(user_id):
    token = secrets.token_hex(16)
    expiration_time = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_PERIOD)
    tokens_collection.update_one({"user_id": user_id}, {"$set": {"token": token, "expiration_time": expiration_time}}, upsert=True)
    return token

# Function to check if a token is valid
def is_valid_token(user_id, user_token):
    stored_token_info = tokens_collection.find_one({"user_id": user_id})
    if stored_token_info and stored_token_info["token"] == user_token:
        return not is_token_expired(user_id)
    return False

# Function to check if a token is expired
def is_token_expired(user_id):
    stored_token_info = tokens_collection.find_one({"user_id": user_id})
    if stored_token_info:
        expiration_time = stored_token_info.get("expiration_time")
        return expiration_time and expiration_time < datetime.now()
    return True

# Function to reset the token verification process
def reset_token_verification(user_id):
    tokens_collection.update_one({"user_id": user_id}, {"$set": {"expiration_time": None}})

# Function to retrieve stored token from MongoDB
def get_stored_token(user_id):
    stored_token_info = tokens_collection.find_one({"user_id": user_id})
    return stored_token_info["token"] if stored_token_info else None


#=====================================================================================##

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


def main():
    updater = Updater(API_ID, API_HASH, use_context=True)
    dp = updater.dispatcher

    # Your existing handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("check", check))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
