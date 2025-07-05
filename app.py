import os
import json
import asyncio
import aiohttp
import random
import string
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
import discord
from discord.ext import commands
import threading
import time

app = Flask(__name__)
CORS(app)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_BASE_URL = "https://pterodactyl.file.properties/api/client"
SERVER_ID = "1a7ce997"

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Channel and file configuration
CHANNEL_ID = 1390794341764567040
CLOUD_POINTS_FILE = "cloud_points.txt"
POINTS_PER_MESSAGE = 5

# In-memory storage for OTPs and user data
user_points = {}
active_otps = {}
user_data_cache = {}


# Load items from JSON
def load_items():
    try:
        with open('items.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


items_data = load_items()


class CloudPointsManager:
    def __init__(self):
        self.points_data = {}
        self.last_update = {}

    async def load_points_from_discord(self):
        """Load points data from Discord channel"""
        try:
            channel = bot.get_channel(CHANNEL_ID)
            if not channel:
                print(f"Channel {CHANNEL_ID} not found")
                return

            # Look for existing cloud_points.txt file
            async for message in channel.history(limit=100):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.filename == CLOUD_POINTS_FILE:
                            content = await attachment.read()
                            self.parse_points_data(content.decode('utf-8'))
                            return

            # If no file exists, create initial file
            await self.create_initial_points_file(channel)

        except Exception as e:
            print(f"Error loading points from Discord: {e}")

    def parse_points_data(self, content):
        """Parse points data from file content"""
        try:
            lines = content.strip().split('\n')
            for line in lines:
                if ':' in line:
                    user_id, points = line.split(':', 1)
                    self.points_data[user_id.strip()] = int(points.strip())
        except Exception as e:
            print(f"Error parsing points data: {e}")

    async def create_initial_points_file(self, channel):
        """Create initial points file in Discord channel"""
        try:
            initial_content = "# Cloud Points Data\n# Format: user_id:points\n"
            with open(CLOUD_POINTS_FILE, 'w') as f:
                f.write(initial_content)

            with open(CLOUD_POINTS_FILE, 'rb') as f:
                await channel.send(
                    "☁️ Cloud Points system initialized!",
                    file=discord.File(f, CLOUD_POINTS_FILE)
                )

            os.remove(CLOUD_POINTS_FILE)

        except Exception as e:
            print(f"Error creating initial points file: {e}")

    async def update_points_file(self, user_id, points_to_add):
        """Update points file in Discord channel"""
        try:
            user_id = str(user_id)
            current_points = self.points_data.get(user_id, 0)
            new_points = current_points + points_to_add
            self.points_data[user_id] = new_points

            # Rate limiting - only update file every 30 seconds per user
            now = time.time()
            if user_id in self.last_update and now - self.last_update[user_id] < 30:
                return new_points

            self.last_update[user_id] = now

            # Generate file content
            content = "# Cloud Points Data\n# Format: user_id:points\n"
            for uid, points in self.points_data.items():
                content += f"{uid}:{points}\n"

            # Upload to Discord
            channel = bot.get_channel(CHANNEL_ID)
            if channel:
                with open(CLOUD_POINTS_FILE, 'w') as f:
                    f.write(content)

                with open(CLOUD_POINTS_FILE, 'rb') as f:
                    await channel.send(
                        f"☁️ Points updated! {user_id} now has {new_points} Cloud Points",
                        file=discord.File(f, CLOUD_POINTS_FILE)
                    )

                os.remove(CLOUD_POINTS_FILE)

            return new_points

        except Exception as e:
            print(f"Error updating points file: {e}")
            return self.points_data.get(user_id, 0)

    def get_points(self, user_id):
        """Get current points for a user"""
        return self.points_data.get(str(user_id), 0)


points_manager = CloudPointsManager()


@bot.event
async def on_ready():
    print(f'{bot.user} has landed! ☁️')
    await points_manager.load_points_from_discord()
    print("Points system initialized")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Award points for messages
    try:
        new_points = await points_manager.update_points_file(message.author.id, POINTS_PER_MESSAGE)
        user_data_cache[str(message.author.id)] = {
            'username': message.author.display_name,
            'avatar': str(message.author.avatar.url) if message.author.avatar else None,
            'points': new_points
        }
    except Exception as e:
        print(f"Error awarding points: {e}")

    await bot.process_commands(message)


def generate_otp():
    """Generate a random 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


async def send_command_to_pterodactyl(command):
    """Send command to Pterodactyl panel"""
    try:
        url = f"{PTERODACTYL_BASE_URL}/servers/{SERVER_ID}/command"
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
        print(f"Error sending command to Pterodactyl: {e}")
        return False


# Flask API Routes

@app.route('/')
def health_check():
    """Health check endpoint"""
    bot_status = "online" if bot.is_ready() else "offline"
    return jsonify({
        'status': 'healthy',
        'bot_status': bot_status,
        'message': '☁️ Cloud Points API is running!'
    })


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Try to get from cache first
        if user_id in user_data_cache:
            return jsonify(user_data_cache[user_id])

        # Get points from manager
        points = points_manager.get_points(user_id)

        # Try to get user info from Discord
        user = bot.get_user(int(user_id))
        if user:
            user_info = {
                'username': user.display_name,
                'avatar': str(user.avatar.url) if user.avatar else None,
                'points': points
            }
            user_data_cache[user_id] = user_info
            return jsonify(user_info)

        return jsonify({
            'username': 'Unknown User',
            'avatar': None,
            'points': points
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        user = bot.get_user(int(user_id))
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Generate OTP
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            'otp': otp,
            'expiry': expiry,
            'used': False
        }

        # Send DM
        asyncio.create_task(send_otp_dm_async(user, otp))

        return jsonify({
            'success': True,
            'message': 'OTP sent to DM',
            'expires_in': '5 minutes'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


async def send_otp_dm_async(user, otp):
    """Send OTP via DM asynchronously"""
    try:
        embed = discord.Embed(
            title="☁️ Cloud Points Shop - OTP Verification",
            description=f"Your OTP code: **{otp}**",
            color=0x00ff00
        )
        embed.add_field(name="Expires in", value="5 minutes", inline=False)
        embed.add_field(name="Note", value="This code can only be used once!", inline=False)

        await user.send(embed=embed)
    except Exception as e:
        print(f"Error sending OTP DM: {e}")


@app.route('/api/shop/<user_id>/<otp>/item/<item_number>/<ingame_name>', methods=['POST'])
def purchase_item(user_id, otp, item_number, ingame_name):
    """Purchase item with OTP verification"""
    try:
        # Verify OTP
        if user_id not in active_otps:
            return jsonify({'error': 'No active OTP found'}), 400

        otp_data = active_otps[user_id]
        if otp_data['otp'] != otp:
            return jsonify({'error': 'Invalid OTP'}), 400

        if datetime.now() > otp_data['expiry']:
            del active_otps[user_id]
            return jsonify({'error': 'OTP expired'}), 400

        if otp_data['used']:
            return jsonify({'error': 'OTP already used'}), 400

        # Check if item exists
        if item_number not in items_data:
            return jsonify({'error': 'Item not found'}), 404

        item = items_data[item_number]
        item_price = int(item['item-price'])

        # Check user points
        user_points = points_manager.get_points(user_id)
        if user_points < item_price:
            return jsonify({'error': 'Insufficient cloud points'}), 400

        # Deduct points
        points_manager.points_data[user_id] = user_points - item_price

        # Mark OTP as used
        active_otps[user_id]['used'] = True

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)

        # Execute command asynchronously
        asyncio.create_task(execute_purchase_command(command, user_id, item, ingame_name))

        return jsonify({
            'success': True,
            'message': f'Successfully purchased {item["item-name"]}',
            'item': item['item-name'],
            'points_remaining': user_points - item_price
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


async def execute_purchase_command(command, user_id, item, ingame_name):
    """Execute purchase command asynchronously"""
    try:
        success = await send_command_to_pterodactyl(command)

        # Send confirmation to user
        user = bot.get_user(int(user_id))
        if user:
            embed = discord.Embed(
                title="☁️ Purchase Successful!",
                description=f"You have successfully purchased **{item['item-name']}**",
                color=0x00ff00
            )
            embed.add_field(name="In-game Name", value=ingame_name, inline=True)
            embed.add_field(name="Status", value="✅ Delivered" if success else "❌ Failed", inline=True)

            await user.send(embed=embed)

    except Exception as e:
        print(f"Error executing purchase command: {e}")


@app.route('/api/item-info/<item_number>')
def get_item_info(item_number):
    """Get item information"""
    try:
        if item_number not in items_data:
            return jsonify({'error': 'Item not found'}), 404

        item = items_data[item_number]
        return jsonify({
            'item_number': item_number,
            'item_name': item['item-name'],
            'item_price': int(item['item-price']),
            'item_icon': item['item-icon']
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/items')
def get_all_items():
    """Get all available items"""
    try:
        formatted_items = []
        for item_number, item in items_data.items():
            formatted_items.append({
                'item_number': item_number,
                'item_name': item['item-name'],
                'item_price': int(item['item-price']),
                'item_icon': item['item-icon']
            })
        return jsonify(formatted_items)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def run_bot():
    """Run the Discord bot"""
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Error running bot: {e}")


if __name__ == '__main__':
    # Start Discord bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Give bot time to start
    time.sleep(3)

    # Start Flask app
    app.run(host='0.0.0.0', port=5000, debug=False)