import os

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
BOT_USERNAME = os.getenv("BOT_USERNAME")
WELCOME_IMAGE_URL = os.getenv("WELCOME_IMAGE_URL")

if not all([TOKEN, ADMIN_ID, CHANNEL_ID, BOT_USERNAME, WELCOME_IMAGE_URL]):
    raise EnvironmentError("One or more environment variables are missing. Please set TOKEN, ADMIN_ID, CHANNEL_ID, BOT_USERNAME, and WELCOME_IMAGE_URL.")

