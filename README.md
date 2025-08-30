# Telegram Vote Bot

A feature-rich Telegram bot for creating and managing polls with advanced functionalities.

## ✨ Features

- **Polls with Images:** Create polls that include a visual component.
- **Unique Share Links:** Each poll generates a unique deep-link for easy sharing.
- **Live Results:** View real-time voting results.
- **Group Tagging:** Automatically tags all members in a group when a poll is created (requires group admin privileges).
- **Channel Forwarding:** Polls and vote notifications are sent to a designated channel.
- **Channel Member-Only Voting:** Restricts voting to members of a specific channel.
- **Welcome Message with Image:** The `/start` command shows a welcome message with a custom image and inline buttons.
- **User-Specific Notifications:** When a user votes, their name and bot's username are included in the channel post.
- **Reactions:** Add reactions like 👍, 👎, ❤️, 😂 to poll posts.
- **Inline Mode:** Use the bot in any chat by typing `@yourbotname`.

## 🚀 Deployment

### 1. Bot Setup

1.  **Create a Bot:** Talk to [@BotFather](https://t.me/BotFather) to create a new bot and get your **TOKEN**.
2.  **Find IDs:** Get your Telegram user ID (`ADMIN_ID`), the ID of the channel (`CHANNEL_ID`), and your bot's username (`BOT_USERNAME`).
3.  **Host Image:** Upload your welcome image to a service like Imgur and get a direct link for `WELCOME_IMAGE_URL`.

### 2. Environment Variables

You must set these variables on your hosting platform (like Render.com) for the bot to run.

- `TOKEN`: Your bot's API token.
- `ADMIN_ID`: Your Telegram user ID.
- `CHANNEL_ID`: The channel where polls will be posted.
- `BOT_USERNAME`: The username of your bot (e.g., `MyVoteBot`).
- `WELCOME_IMAGE_URL`: The URL of your welcome image.

### 3. Deploy on Render.com

1.  **Fork this repository.**
2.  **Create a New Web Service:** On the Render dashboard, click **New +** and select **Web Service**.
3.  **Connect GitHub:** Connect your GitHub account and select your forked repository.
4.  **Configuration:** Render will use the `render.yaml` file to configure everything automatically.
5.  **Add Environment Variables:** Go to the `Advanced` settings and add the environment variables listed above.
6.  **Deploy:** Click **Create Web Service** to start the deployment.

---
