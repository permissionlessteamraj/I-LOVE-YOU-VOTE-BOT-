import logging
import sqlite3
import uuid
import re
import time
from datetime import datetime, timedelta
import random

# Make sure you have a config.py file with these variables
from config import TOKEN, ADMIN_ID, CHANNEL_ID, BOT_USERNAME, WELCOME_IMAGE_URL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, InputFile, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

# States for poll creation conversation
POLL_TITLE, POLL_OPTIONS, POLL_IMAGE = range(3)

# State for romantic chat conversation
ROMANTIC_CHAT = 4

# Anti-flood settings
FLOOD_THRESHOLD = 5  # Max messages in a time interval
FLOOD_TIME_WINDOW = 5  # Time window in seconds
user_last_messages = {}

# --- Database Setup ---
conn = sqlite3.connect('bot_data.db')
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS polls (
        poll_id TEXT PRIMARY KEY,
        creator_id INTEGER,
        creator_username TEXT,
        title TEXT,
        image_url TEXT
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS options (
        poll_id TEXT,
        option_index INTEGER,
        option_text TEXT,
        PRIMARY KEY (poll_id, option_index),
        FOREIGN KEY (poll_id) REFERENCES polls(poll_id) ON DELETE CASCADE
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS votes (
        poll_id TEXT,
        voter_id INTEGER,
        voter_username TEXT,
        option_index INTEGER,
        FOREIGN KEY (poll_id) REFERENCES polls(poll_id) ON DELETE CASCADE
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS group_settings (
        chat_id INTEGER PRIMARY KEY,
        welcome_message TEXT,
        welcome_image_url TEXT
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS active_mutes (
        chat_id INTEGER,
        user_id INTEGER,
        mute_until INTEGER,
        PRIMARY KEY (chat_id, user_id)
    )
''')
conn.commit()

# --- Helper Functions ---
def get_group_settings(chat_id):
    c.execute("SELECT welcome_message, welcome_image_url FROM group_settings WHERE chat_id = ?", (chat_id,))
    return c.fetchone()

def update_group_settings(chat_id, welcome_message, welcome_image_url):
    c.execute("REPLACE INTO group_settings VALUES (?, ?, ?)", (chat_id, welcome_message, welcome_image_url))
    conn.commit()

def add_mute(chat_id, user_id, duration_minutes):
    mute_until = int(time.time()) + duration_minutes * 60
    c.execute("REPLACE INTO active_mutes VALUES (?, ?, ?)", (chat_id, user_id, mute_until))
    conn.commit()

def remove_mute(chat_id, user_id):
    c.execute("DELETE FROM active_mutes WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    conn.commit()

def is_user_muted(chat_id, user_id):
    c.execute("SELECT mute_until FROM active_mutes WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
    result = c.fetchone()
    if result:
        mute_until = result[0]
        if time.time() < mute_until:
            return True
        else:
            remove_mute(chat_id, user_id)
            return False
    return False

def generate_poll_id():
    return str(uuid.uuid4())

def get_poll_data(poll_id):
    c.execute("SELECT * FROM polls WHERE poll_id = ?", (poll_id,))
    poll = c.fetchone()
    if not poll:
        return None, None, None, None
    _, creator_id, creator_username, title, image_url = poll
    c.execute("SELECT option_text FROM options WHERE poll_id = ? ORDER BY option_index", (poll_id,))
    options = [row[0] for row in c.fetchall()]
    return title, creator_username, options, image_url

def get_vote_counts(poll_id):
    c.execute("SELECT option_index, COUNT(*) FROM votes WHERE poll_id = ? GROUP BY option_index", (poll_id,))
    vote_counts = {row[0]: row[1] for row in c.fetchall()}
    return vote_counts

def create_poll_message_and_keyboard(poll_id, title, options, vote_counts, is_results_mode=False):
    total_votes = sum(vote_counts.values())
    poll_text = f"📊 **{title}**\n\n"
    keyboard_buttons = []
    for i, option_text in enumerate(options):
        count = vote_counts.get(i, 0)
        percentage = (count / total_votes) * 100 if total_votes > 0 else 0
        if is_results_mode:
            poll_text += f"**{option_text}** - {count} votes ({percentage:.2f}%)\n"
        callback_data = f"vote_{poll_id}_{i}"
        keyboard_buttons.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    reaction_buttons = [
        InlineKeyboardButton("👍", callback_data=f"react_{poll_id}_like"),
        InlineKeyboardButton("👎", callback_data=f"react_{poll_id}_dislike"),
        InlineKeyboardButton("❤️", callback_data=f"react_{poll_id}_heart"),
        InlineKeyboardButton("😂", callback_data=f"react_{poll_id}_laugh")
    ]
    keyboard_rows = keyboard.inline_keyboard + [reaction_buttons]
    vote_count_button = InlineKeyboardButton(f"Total Votes: {total_votes}", callback_data=f"results_{poll_id}")
    keyboard_rows.append([vote_count_button])
    return poll_text, InlineKeyboardMarkup(keyboard_rows)

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        poll_id = args[0]
        await handle_deep_link(update, context, poll_id)
        return

    caption = "👋 **Welcome to the Group Help Bot!**\n\nI can help you manage your group, create polls, and more.\n\nUse the buttons below to get started."
    keyboard = [
        [InlineKeyboardButton("➕ Create Poll", callback_data="create_poll")],
        [InlineKeyboardButton("❤️ Romantic Chat", callback_data="start_romantic_chat")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    await update.message.reply_photo(
        photo=WELCOME_IMAGE_URL,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**Group Help Bot Commands**\n\n"
        "**User Commands:**\n"
        "/start - Get the welcome message.\n"
        "/help - Show this help message.\n"
        "/romantic - Start a romantic chat with me.\n\n"
        "**Poll Commands:**\n"
        "/create - Start creating a new poll.\n\n"
        "**Admin Commands:**\n"
        "/setwelcome [message] - Set a custom welcome message.\n"
        "/kick [user] - Kick a user from the group.\n"
        "/ban [user] - Ban a user from the group.\n"
        "/mute [user] [duration] - Mute a user for a specified duration (e.g., /mute @user 30m).\n"
        "/unmute [user] - Unmute a user.\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# --- Romantic Chatbot Logic ---
async def start_romantic_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(f"Hello, my love. It’s so good to talk to you, {user_name}. What's on your mind? ✨")
    return ROMANTIC_CHAT

def get_romantic_response(user_input: str) -> str:
    user_input = user_input.lower()
    responses = {
        "love": ["My heart beats only for you. You are the most beautiful person in the world to me. ❤️", "You are the reason for my happiness. Every moment with you is a dream come true."],
        "miss": ["I miss you more than words can say. Every moment without you feels incomplete. 💖", "The world feels empty when you're not around. I can't wait to see you again."],
        "hi": ["Hi there, sweetheart. I'm so glad you're here. Tell me something lovely. 😊", "Hello, my darling. Your presence fills me with joy."],
        "bye": ["Goodbye, my darling. Don't be a stranger, okay? My heart will be waiting for you. 😘", "Farewell, my love. I'll be thinking of you until we speak again."],
    }
    for keyword, response_list in responses.items():
        if keyword in user_input:
            return random.choice(response_list)
    return "Oh, my darling. Tell me more. Your words are music to my ears."

async def handle_romantic_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    response = get_romantic_response(user_input)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Stop the chat", callback_data="end_romantic_chat")]
    ])
    
    await update.message.reply_text(response, reply_markup=keyboard)
    return ROMANTIC_CHAT

async def end_romantic_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("The romantic chat has ended. If you need me, just say the word. 🥰")
    return ConversationHandler.END

# --- Poll Bot Logic ---
async def create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("What's the title of your poll?")
    return POLL_TITLE

async def receive_poll_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text("Great! Now send me the options, one per line.")
    return POLL_OPTIONS

async def receive_poll_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    options = [opt.strip() for opt in update.message.text.split('\n') if opt.strip()]
    if len(options) < 2:
        await update.message.reply_text("Please provide at least two options. Try again.")
        return POLL_OPTIONS
    
    context.user_data['options'] = options
    await update.message.reply_text("Please send an image URL for the poll.")
    return POLL_IMAGE

async def receive_poll_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    image_url = update.message.text
    poll_id = generate_poll_id()
    creator_id = update.message.from_user.id
    creator_username = update.message.from_user.username
    title = context.user_data['title']
    options = context.user_data['options']

    c.execute("INSERT INTO polls VALUES (?, ?, ?, ?, ?)", (poll_id, creator_id, creator_username, title, image_url))
    for i, opt_text in enumerate(options):
        c.execute("INSERT INTO options VALUES (?, ?, ?)", (poll_id, i, opt_text))
    conn.commit()

    vote_counts = get_vote_counts(poll_id)
    poll_text, keyboard = create_poll_message_and_keyboard(poll_id, title, options, vote_counts)
    
    await update.message.reply_text(
        f"Poll created! Share this link:\nhttps://t.me/{BOT_USERNAME}?start={poll_id}",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        channel_post_caption = (
            f"**New Poll by @{creator_username}**\n\n"
            f"{poll_text}"
            f"\n\n_This post is generated by @{BOT_USERNAME}_"
        )
        await context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=image_url,
            caption=channel_post_caption,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    poll_id = parts[1]
    option_index = int(parts[2])
    voter_id = query.from_user.id
    voter_username = query.from_user.username
    
    c.execute("SELECT * FROM votes WHERE poll_id = ? AND voter_id = ?", (poll_id, voter_id))
    if c.fetchone():
        await query.message.reply_text("You have already voted in this poll. Here are the live results.")
    else:
        c.execute("INSERT INTO votes VALUES (?, ?, ?, ?)", (poll_id, voter_id, voter_username, option_index))
        conn.commit()
        await query.message.reply_text("Vote received! Here are the live results.")
    await show_results(update, context, poll_id=poll_id)

async def show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id=None):
    if not poll_id:
        query = update.callback_query
        poll_id = query.data.split('_')[1]
        
    title, creator_username, options, image_url = get_poll_data(poll_id)
    if not title:
        return
        
    vote_counts = get_vote_counts(poll_id)
    poll_text, _ = create_poll_message_and_keyboard(poll_id, title, options, vote_counts, is_results_mode=True)
    await update.effective_message.edit_caption(
        caption=f"**Live Results**\n\n{poll_text}\n\n_This post is generated by @{BOT_USERNAME}_",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE, poll_id: str):
    title, creator_username, options, image_url = get_poll_data(poll_id)
    if not title:
        await update.message.reply_text("This poll doesn't exist.")
        return
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['member', 'creator', 'administrator']:
            vote_counts = get_vote_counts(poll_id)
            poll_text, keyboard = create_poll_message_and_keyboard(poll_id, title, options, vote_counts)
            await update.message.reply_text("You've been successfully redirected to the channel. Vote there!")
            channel_post_caption = (
                f"**A new participant has joined!**\n\n"
                f"**{update.effective_user.full_name}** has followed the link from **@{BOT_USERNAME}**.\n\n"
                f"Check out this poll:\n\n{poll_text}"
            )
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=image_url,
                caption=channel_post_caption,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("You must be a member of our channel to vote. Please join first and try again.")
    except Exception as e:
        logger.error(f"Failed to check channel membership: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    results = []
    if query:
        c.execute("SELECT poll_id, title FROM polls WHERE title LIKE ?", (f"%{query}%",))
        for poll_id, title in c.fetchall():
            results.append(
                InlineQueryResultArticle(
                    id=poll_id,
                    title=title,
                    input_message_content=InputTextMessageContent(
                        message_text=f"Check out this poll: https://t.me/{BOT_USERNAME}?start={poll_id}"
                    ),
                    description=f"Click to share poll: {title}"
                )
            )
    await update.inline_query.answer(results)

# --- Group Help Bot Logic ---
async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        chat_id = update.effective_chat.id
        group_settings = get_group_settings(chat_id)
        if group_settings:
            welcome_message = group_settings[0]
            welcome_image_url = group_settings[1]
        else:
            welcome_message = "Welcome to the group, {name}!"
            welcome_image_url = WELCOME_IMAGE_URL

        welcome_text = welcome_message.format(name=member.full_name)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join our Channel", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")]
        ])
        if welcome_image_url:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=welcome_image_url,
                caption=welcome_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )

async def left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.left_chat_member.is_bot:
        return
    await update.message.reply_text(f"Goodbye, {update.message.left_chat_member.full_name}!")

# Admin functions
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in a group.")
        return
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    if update.effective_user.id not in [admin.user.id for admin in admins]:
        await update.message.reply_text("You must be an admin to use this command.")
        return

    welcome_message = " ".join(context.args)
    if not welcome_message:
        await update.message.reply_text("Please provide a welcome message. Example: `/setwelcome Welcome {name}!`")
        return
    update_group_settings(update.effective_chat.id, welcome_message, WELCOME_IMAGE_URL)
    await update.message.reply_text("Welcome message updated successfully.")

async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in a group.")
        return
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    if update.effective_user.id not in [admin.user.id for admin in admins]:
        await update.message.reply_text("You must be an admin to use this command.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user's message to kick them.")
        return
    user_to_kick = update.message.reply_to_message.from_user
    try:
        await context.bot.kick_chat_member(update.effective_chat.id, user_to_kick.id)
        await update.message.reply_text(f"Kicked {user_to_kick.full_name}.")
    except Exception as e:
        await update.message.reply_text(f"Could not kick user. Error: {e}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in a group.")
        return
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    if update.effective_user.id not in [admin.user.id for admin in admins]:
        await update.message.reply_text("You must be an admin to use this command.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user's message to ban them.")
        return
    user_to_ban = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_to_ban.id)
        await update.message.reply_text(f"Banned {user_to_ban.full_name}.")
    except Exception as e:
        await update.message.reply_text(f"Could not ban user. Error: {e}")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in ['group', 'supergroup']:
        await update.message.reply_text("This command can only be used in a group.")
        return
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    if update.effective_user.id not in [admin.user.id for admin in admins]:
        await update.message.reply_text("You must be an admin to use this command.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to a user's message to mute them.")
        return
    user_to_mute = update.message.reply_to_message.from_user
    duration_minutes = 10 
    if context.args and context.args[0].isdigit():
        duration_minutes = int(context.args[0])
    try:
        until_date = datetime.now() + timedelta(minutes=duration_minutes)
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_to_mute.id,
            until_date=until_date,
            permissions={"can_send_messages": False}
        )
        add_mute(update.effective_chat.id, user_to_mute.id, duration_minutes)
        await update.message.reply_text(f"Muted {user_to_mute.full_name} for {duration_minutes} minutes.")
    except Exception as e:
        await update.message.reply_text(f"Could not mute user. Error: {e}")

async def anti_flood_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    current_time = time.time()
    if user_id not in user_last_messages:
        user_last_messages[user_id] = []
    user_last_messages[user_id].append(current_time)
    user_last_messages[user_id] = [t for t in user_last_messages[user_id] if current_time - t < FLOOD_TIME_WINDOW]
    if len(user_last_messages[user_id]) > FLOOD_THRESHOLD:
        await mute_user_for_flood(update, context, user_id, chat_id)

async def mute_user_for_flood(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, chat_id):
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions={"can_send_messages": False}
        )
        add_mute(chat_id, user_id, 10)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"**@{update.effective_user.username}** has been muted for spamming.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to mute user: {e}")

# --- Main Function to Run Bot ---
def main():
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler for poll creation
    poll_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('create', create),
            CallbackQueryHandler(create, pattern="^create_poll$")
        ],
        states={
            POLL_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_poll_title)],
            POLL_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_poll_options)],
            POLL_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_poll_image)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    # Conversation handler for romantic chat
    romantic_chat_handler = ConversationHandler(
        entry_points=[
            CommandHandler('romantic', start_romantic_chat),
            CallbackQueryHandler(start_romantic_chat, pattern="^start_romantic_chat$")
        ],
        states={
            ROMANTIC_CHAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_romantic_message),
                CallbackQueryHandler(end_romantic_chat, pattern="^end_romantic_chat$")
            ],
        },
        fallbacks=[CommandHandler('end', end_romantic_chat)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(poll_conv_handler)
    application.add_handler(romantic_chat_handler)
    application.add_handler(CallbackQueryHandler(vote_callback, pattern=re.compile(r'^vote_.*')))
    application.add_handler(CallbackQueryHandler(show_results, pattern=re.compile(r'^results_.*')))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, left_member))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_flood_check))

    application.run_polling(poll_interval=3)

if __name__ == '__main__':
    main()
