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

# Use motor for asynchronous MongoDB operations
dbclient = motor_asyncio.AsyncIOMotorClient(DB_URI)
database = dbclient[DB_NAME]
tokens_collection = database["tokens"]
user_data = database['users']

# Token expiration period (1 day in seconds)
TOKEN_EXPIRATION_PERIOD = 86

# Function to get unused tokens for a user

async def get_unused_token(user_id):
    user_token = await tokens_collection.find_one({"user_id": user_id}, {"expiry_time": 1})
    
    if user_token and "expiry_time" in user_token:
        if user_token["expiry_time"] > datetime.now():
            return user_token["token"]
    return None
    
        
# Function to generate a token for a user
async def generate_token(user_id):
    token = secrets.token_hex(16)  # Generate a random token
    expiry_time = datetime.now() + timedelta(hours=24)  # Set the token expiration time (24 hours)
    
    # Save the token and its expiration time in the database for the user
    await tokens_collection.insert_one({"user_id": user_id, "token": token, "expiry_time": expiry_time})
    return token

# Function to check if a token is valid for a user
async def verify_token(user_id, provided_token):
    user_token = await tokens_collection.find_one({"user_id": user_id})
    
    if user_token and user_token["token"] == provided_token and user_token["expiry_time"] > datetime.now():
        return True  # Token is valid
    else:
        return False  # Token is invalid or expired


# Function to handle the start command logic
async def handle_start_command(client: Client, message: Message):
    id = message.from_user.id
    if not await present_user(id):
        try:
            await add_user(id)
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
                caption = CUSTOM_CAPTION.format(previouscaption="" if not msg.caption else msg.caption.html,
                                                filename=msg.document.file_name)
            else:
                caption = "" if not msg.caption else msg.caption.html

            if DISABLE_CHANNEL_BUTTON:
                reply_markup = msg.reply_markup
            else:
                reply_markup = None

            try:
                await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML,
                               reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.x)
                await msg.copy(chat_id=message.from_user.id, caption=caption, parse_mode=ParseMode.HTML,
                               reply_markup=reply_markup, protect_content=PROTECT_CONTENT)
            except:
                pass
        return
    else:
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("😊 About Me", callback_data="about"),
                    InlineKeyboardButton("🔒 Close", callback_data="close")
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

# Modify your command handler to include token verification
@Bot.on_message(filters.command('start') & filters.private & subscribed)
async def start_command(client: Client, message: Message):
    id = message.from_user.id
    user_has_token = await verify_token(id, "")
    
    if not user_has_token:
        # Check if a token was previously generated but not used
        unused_token = await get_unused_token(id)
        if unused_token:
            await message.reply_text(f"Here's your unused token: {unused_token}")
            return
        else:
            # Generate a new token for the user
            new_token = await generate_token(id)
            await message.reply_text(f"Here's your new token: {new_token}")
            return
    
    text = message.text
    if len(text) > 7:
        try:
            provided_token = text.split(" ", 1)[1]
            # Verify the provided token
            is_valid = await verify_token(id, provided_token)
            if is_valid:
                # Token is valid, execute the start command logic
                await handle_start_command(client, message)
            else:
                # Token is invalid or expired, return a new token
                new_token = await generate_token(id)
                await message.reply_text(f"Invalid or expired token. Here's a new token: {new_token}")
                return
        except IndexError:
            return
        except Exception as e:
            print(e)  # Handle exceptions accordingly
           
# ... (Your existing code remains unchanged up to the function definitions)

# Function to check the remaining time for a user's token
async def check_token(client: Client, message: Message):
    id = message.from_user.id
    user_id = message.from_user.id
    user_token = await tokens_collection.find_one({"user_id": id})
    
    if user_token:
        remaining_time = user_token["expiry_time"] - datetime.now()
        remaining_hours = remaining_time.total_seconds() // 3600
        remaining_minutes = (remaining_time.total_seconds() % 3600) // 60
        
        await message.reply_text(f"Your token is valid. Time remaining: {int(remaining_hours)} hours and {int(remaining_minutes)} minutes.")
    else:
        await message.reply_text("You don't have a valid token.")

# ... (Your other existing functions)

@Bot.on_message(filters.command('check') & filters.private)
async def check_command(client: Client, message: Message):
    await check_token(client, message)

# ... (Your remaining code)


    
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
