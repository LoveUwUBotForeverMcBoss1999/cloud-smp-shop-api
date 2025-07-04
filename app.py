import os
import json
import random
import string
import asyncio
import aiohttp
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
import discord
from discord.ext import commands
import threading

app = Flask(__name__)
CORS(app)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = os.getenv('PTERODACTYL_SERVER_ID', '1a7ce997')
PTERODACTYL_BASE_URL = os.getenv('PTERODACTYL_BASE_URL', 'https://pterodactyl.file.properties')

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Storage for OTPs (in production, use Redis or database)
otps = {}

# Channel ID where cloud_points.txt is stored
CLOUD_POINTS_CHANNEL_ID = 1390794341764567040


class CloudPointsManager:
    def __init__(self):
        self.user_points = {}
        self.points_file_message = None

    async def load_points_from_discord(self):
        """Load points from Discord channel"""
        try:
            channel = bot.get_channel(CLOUD_POINTS_CHANNEL_ID)
            if not channel:
                return

            # Look for existing cloud_points.txt
            async for message in channel.history(limit=100):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.filename == 'cloud_points.txt':
                            self.points_file_message = message
                            content = await attachment.read()
                            self.user_points = json.loads(content.decode('utf-8'))
                            return

            # If no file found, create one
            await self.create_initial_points_file(channel)

        except Exception as e:
            print(f"Error loading points: {e}")

    async def create_initial_points_file(self, channel):
        """Create initial cloud_points.txt file"""
        try:
            initial_data = {}
            with open('temp_cloud_points.txt', 'w') as f:
                json.dump(initial_data, f)

            with open('temp_cloud_points.txt', 'rb') as f:
                file = discord.File(f, filename='cloud_points.txt')
                message = await channel.send('☁️ Cloud Points Database initialized!', file=file)
                self.points_file_message = message

            os.remove('temp_cloud_points.txt')

        except Exception as e:
            print(f"Error creating initial file: {e}")

    async def update_points_file(self):
        """Update the Discord file with current points"""
        try:
            if not self.points_file_message:
                return

            with open('temp_cloud_points.txt', 'w') as f:
                json.dump(self.user_points, f, indent=2)

            with open('temp_cloud_points.txt', 'rb') as f:
                file = discord.File(f, filename='cloud_points.txt')
                channel = bot.get_channel(CLOUD_POINTS_CHANNEL_ID)
                new_message = await channel.send('☁️ Cloud Points Database updated!', file=file)

                # Delete old message
                if self.points_file_message:
                    try:
                        await self.points_file_message.delete()
                    except:
                        pass

                self.points_file_message = new_message

            os.remove('temp_cloud_points.txt')

        except Exception as e:
            print(f"Error updating points file: {e}")

    async def add_points(self, user_id, points=5):
        """Add points to user"""
        user_id = str(user_id)
        if user_id not in self.user_points:
            self.user_points[user_id] = 0

        self.user_points[user_id] += points
        await self.update_points_file()

    async def deduct_points(self, user_id, points):
        """Deduct points from user"""
        user_id = str(user_id)
        if user_id not in self.user_points:
            return False

        if self.user_points[user_id] < points:
            return False

        self.user_points[user_id] -= points
        await self.update_points_file()
        return True

    def get_points(self, user_id):
        """Get user points"""
        return self.user_points.get(str(user_id), 0)


points_manager = CloudPointsManager()


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    await points_manager.load_points_from_discord()


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Add 5 cloud points for each message
    await points_manager.add_points(message.author.id, 5)

    await bot.process_commands(message)


def load_items():
    """Load items from items.json"""
    try:
        with open('items.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def generate_otp():
    """Generate 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


async def send_pterodactyl_command(command):
    """Send command to Pterodactyl panel"""
    try:
        url = f"{PTERODACTYL_BASE_URL}/api/client/servers/{PTERODACTYL_SERVER_ID}/command"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }
        data = {'command': command}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                return response.status == 204
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


# Flask API Routes

@app.route('/')
def health_check():
    """Health check endpoint"""
    bot_status = "connected" if bot.is_ready() else "disconnected"
    return jsonify({
        "status": "healthy",
        "bot_status": bot_status,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/user/<int:user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        user = bot.get_user(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        points = points_manager.get_points(user_id)

        return jsonify({
            "discord_id": user_id,
            "username": user.name,
            "avatar": str(user.avatar.url) if user.avatar else str(user.default_avatar.url),
            "cloud_points": points
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<int:user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        user = bot.get_user(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Store OTP with expiry
        otps[user_id] = {
            "code": otp,
            "expiry": expiry,
            "used": False
        }

        # Send DM
        asyncio.create_task(
            user.send(f"🔐 Your OTP code for ☁️ Cloud Points shop: **{otp}**\n\nThis code expires in 5 minutes."))

        return jsonify({
            "success": True,
            "message": "OTP sent to user's DM",
            "expires_at": expiry.isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<int:user_id>/<otp>/item/<int:item_number>/<ingame_name>')
def purchase_item(user_id, otp, item_number, ingame_name):
    """Purchase item with OTP verification"""
    try:
        # Verify OTP
        if user_id not in otps:
            return jsonify({"error": "No OTP found"}), 400

        otp_data = otps[user_id]
        if otp_data["code"] != otp:
            return jsonify({"error": "Invalid OTP"}), 400

        if datetime.now() > otp_data["expiry"]:
            return jsonify({"error": "OTP expired"}), 400

        if otp_data["used"]:
            return jsonify({"error": "OTP already used"}), 400

        # Load items
        items = load_items()
        item_key = str(item_number)

        if item_key not in items:
            return jsonify({"error": "Item not found"}), 404

        item = items[item_key]
        item_price = int(item["item-price"])

        # Check if user has enough points
        user_points = points_manager.get_points(user_id)
        if user_points < item_price:
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Deduct points
        success = asyncio.run(points_manager.deduct_points(user_id, item_price))
        if not success:
            return jsonify({"error": "Failed to deduct points"}), 500

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)
        command_success = asyncio.run(send_pterodactyl_command(command))

        if not command_success:
            # Refund points if command failed
            asyncio.run(points_manager.add_points(user_id, item_price))
            return jsonify({"error": "Failed to execute item command"}), 500

        # Mark OTP as used
        otps[user_id]["used"] = True

        return jsonify({
            "success": True,
            "message": f"Successfully purchased {item['item-name']}",
            "item": item["item-name"],
            "cost": item_price,
            "remaining_points": points_manager.get_points(user_id)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/item-info/<int:item_number>')
def get_item_info(item_number):
    """Get item information"""
    try:
        items = load_items()
        item_key = str(item_number)

        if item_key not in items:
            return jsonify({"error": "Item not found"}), 404

        item = items[item_key]

        return jsonify({
            "item_id": item_number,
            "item_name": item["item-name"],
            "item_price": int(item["item-price"]),
            "item_icon": item["item-icon"],
            "item_cmd": item["item-cmd"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/items')
def get_all_items():
    """Get all available items"""
    try:
        items = load_items()
        formatted_items = []

        for item_id, item_data in items.items():
            formatted_items.append({
                "item_id": int(item_id),
                "item_name": item_data["item-name"],
                "item_price": int(item_data["item-price"]),
                "item_icon": item_data["item-icon"]
            })

        return jsonify({"items": formatted_items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_bot():
    """Run the Discord bot"""
    bot.run(DISCORD_TOKEN)


if __name__ == '__main__':
    # Start Discord bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Run Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)