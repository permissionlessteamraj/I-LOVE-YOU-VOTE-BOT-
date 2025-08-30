import logging
import sqlite3
import uuid
import re
from config import TOKEN, ADMIN_ID, CHANNEL_ID, BOT_USERNAME, WELCOME_IMAGE_URL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, InlineQueryResultArticle, InputTextMessageContent, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, ConversationHandler, Filters
from telegram import ReplyKeyboardMarkup, KeyboardButton
from telegram import InlineQueryResultPhoto
from telegram import InlineQueryResultArticle, InputTextMessageContent

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

# States for conversation
POLL_TITLE, POLL_OPTIONS = range(2)

# Database setup
conn = sqlite3.connect('votes.db')
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
conn.commit()

# Helper function to generate a unique poll ID
def generate_poll_id():
    return str(uuid.uuid4())

# Helper function to get poll data
def get_poll_data(poll_id):
    c.execute("SELECT * FROM polls WHERE poll_id = ?", (poll_id,))
    poll = c.fetchone()
    if not poll:
        return None, None, None, None
    _, creator_id, creator_username, title, image_url = poll

    c.execute("SELECT option_text FROM options WHERE poll_id = ? ORDER BY option_index", (poll_id,))
    options = [row[0] for row in c.fetchall()]

    return title, creator_username, options, image_url

# Helper function to get vote counts for a poll
def get_vote_counts(poll_id):
    c.execute("SELECT option_index, COUNT(*) FROM votes WHERE poll_id = ? GROUP BY option_index", (poll_id,))
    vote_counts = {row[0]: row[1] for row in c.fetchall()}
    return vote_counts

# Helper function to create the poll message and keyboard
def create_poll_message_and_keyboard(poll_id, title, options, vote_counts, is_results_mode=False):
    total_votes = sum(vote_counts.values())
    
    poll_text = f"📊 **{title}**\n\n"
    keyboard_buttons = []

    for i, option_text in enumerate(options):
        count = vote_counts.get(i, 0)
        percentage = (count / total_votes) * 100 if total_votes > 0 else 0
        
        if is_results_mode:
            poll_text += f"**{option_text}** - {count} votes ({percentage:.2f}%)\n"
        else:
            poll_text += f"{option_text}\n"
        
        callback_data = f"vote_{poll_id}_{i}"
        keyboard_buttons.append([InlineKeyboardButton(option_text, callback_data=callback_data)])
    
    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    # Add reactions and share button
    reaction_buttons = [
        InlineKeyboardButton("👍", callback_data=f"react_{poll_id}_like"),
        InlineKeyboardButton("👎", callback_data=f"react_{poll_id}_dislike"),
        InlineKeyboardButton("❤️", callback_data=f"react_{poll_id}_heart"),
        InlineKeyboardButton("😂", callback_data=f"react_{poll_id}_laugh")
    ]
    keyboard_rows = keyboard.inline_keyboard + [reaction_buttons]

    # Add vote count button
    vote_count_button = InlineKeyboardButton(f"Total Votes: {total_votes}", callback_data=f"results_{poll_id}")
    keyboard_rows.append([vote_count_button])

    return poll_text, InlineKeyboardMarkup(keyboard_rows)

# Command handlers
def start(update: Update, context):
    args = context.args
    if args:
        poll_id = args[0]
        handle_deep_link(update, context, poll_id)
        return

    # Welcome message with image and inline buttons
    caption = "👋 **Welcome to the Vote Bot!**\n\nI can help you create custom polls with images and send them to your channels and groups.\n\nUse the buttons below to get started."
    keyboard = [
        [InlineKeyboardButton("➕ Create Poll", callback_data="create_poll")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    
    # Send photo with caption and inline keyboard
    update.message.reply_photo(
        photo=WELCOME_IMAGE_URL,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

def handle_deep_link(update: Update, context, poll_id):
    # This is where we handle the deep link logic
    title, creator_username, options, image_url = get_poll_data(poll_id)
    if not title:
        update.message.reply_text("This poll doesn't exist.")
        return

    # Check if the user is a channel member
    user_id = update.effective_user.id
    try:
        member = context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['member', 'creator', 'administrator']:
            vote_counts = get_vote_counts(poll_id)
            poll_text, keyboard = create_poll_message_and_keyboard(poll_id, title, options, vote_counts)
            
            # Send poll to the channel with user's name
            poll_text = f"**{update.effective_user.full_name}** has joined and voted on a poll!\n\n" + poll_text
            context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=image_url,
                caption=poll_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )

            update.message.reply_text("You've been successfully redirected to the channel. Vote there!")
        else:
            update.message.reply_text("You must be a member of our channel to vote. Please join first and try again.")
    except Exception as e:
        logger.error(f"Failed to check channel membership: {e}")
        update.message.reply_text("An error occurred. Please try again later.")

def create(update: Update, context):
    update.message.reply_text(
        "What's the title of your poll? (e.g., *What's your favorite color?*)"
    )
    return POLL_TITLE

def receive_poll_title(update: Update, context):
    context.user_data['title'] = update.message.text
    update.message.reply_text(
        "Great! Now send me the options, one per line. (e.g., *Red, Blue, Green*)"
    )
    return POLL_OPTIONS

def receive_poll_options(update: Update, context):
    options = [opt.strip() for opt in update.message.text.split('\n') if opt.strip()]
    if len(options) < 2:
        update.message.reply_text("Please provide at least two options. Try again.")
        return POLL_OPTIONS
    
    context.user_data['options'] = options
    
    poll_id = generate_poll_id()
    creator_id = update.message.from_user.id
    creator_username = update.message.from_user.username
    title = context.user_data['title']
    image_url = "https://example.com/default_poll_image.jpg" # Placeholder for an image
    
    # Insert into database
    c.execute("INSERT INTO polls VALUES (?, ?, ?, ?, ?)", (poll_id, creator_id, creator_username, title, image_url))
    for i, opt_text in enumerate(options):
        c.execute("INSERT INTO options VALUES (?, ?, ?)", (poll_id, i, opt_text))
    conn.commit()

    # Create and send the poll
    vote_counts = get_vote_counts(poll_id)
    poll_text, keyboard = create_poll_message_and_keyboard(poll_id, title, options, vote_counts)
    
    # Add group tagging and user information
    group_members_tag = "@all" # Placeholder for a custom tagging method in groups
    poll_text = f"**New Poll from @{creator_username}**\n{group_members_tag}\n\n" + poll_text
    
    # Post the poll to the channel
    channel_post_message = f"**New Poll by @{creator_username}**\n\n"
    channel_post_message += poll_text
    channel_post_message += f"\n\n_This post is generated by @{BOT_USERNAME}_"
    
    try:
        context.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=image_url,
            caption=channel_post_message,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to post to channel: {e}")

    update.message.reply_text(
        f"Poll created! Share this link:\nhttps://t.me/{BOT_USERNAME}?start={poll_id}",
        parse_mode=ParseMode.MARKDOWN
    )

    context.user_data.clear()
    return ConversationHandler.END

def vote_callback(update: Update, context):
    query = update.callback_query
    query.answer()
    
    parts = query.data.split('_')
    poll_id = parts[1]
    option_index = int(parts[2])
    voter_id = query.from_user.id
    voter_username = query.from_user.username
    
    # Check if user has already voted
    c.execute("SELECT * FROM votes WHERE poll_id = ? AND voter_id = ?", (poll_id, voter_id))
    if c.fetchone():
        query.edit_message_text("You have already voted in this poll. Here are the live results.")
    else:
        c.execute("INSERT INTO votes VALUES (?, ?, ?, ?)", (poll_id, voter_id, voter_username, option_index))
        conn.commit()
        query.edit_message_text("Vote received! Here are the live results.")

    # Show live results
    show_results(update, context, poll_id=poll_id)

def show_results(update: Update, context, poll_id=None):
    if not poll_id:
        query = update.callback_query
        poll_id = query.data.split('_')[1]
        
    title, creator_username, options, image_url = get_poll_data(poll_id)
    if not title:
        return
        
    vote_counts = get_vote_counts(poll_id)
    
    # Create results message
    poll_text, _ = create_poll_message_and_keyboard(poll_id, title, options, vote_counts, is_results_mode=True)
    
    # Update the message with new results
    update.effective_message.edit_caption(
        caption=f"**Live Results**\n\n{poll_text}\n\n_This post is generated by @{BOT_USERNAME}_",
        parse_mode=ParseMode.MARKDOWN
    )

def inline_query(update: Update, context):
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
    
    # Add an option to create a new poll in inline mode
    results.append(
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Create a New Poll",
            input_message_content=InputTextMessageContent(
                message_text="/create"
            ),
            description="Start a new poll from scratch."
        )
    )
    
    update.inline_query.answer(results)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create, pattern="^create_poll$"), CommandHandler('create', create)],
        states={
            POLL_TITLE: [MessageHandler(Filters.text & ~Filters.command, receive_poll_title)],
            POLL_OPTIONS: [MessageHandler(Filters.text & ~Filters.command, receive_poll_options)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )

    dp.add_handler(CommandHandler("start", start, pass_args=True))
    dp.add_handler(CommandHandler("help", lambda u, c: start(u, c)))
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(vote_callback, pattern=re.compile(r'^vote_.*')))
    dp.add_handler(CallbackQueryHandler(show_results, pattern=re.compile(r'^results_.*')))
    dp.add_handler(InlineQueryHandler(inline_query))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

