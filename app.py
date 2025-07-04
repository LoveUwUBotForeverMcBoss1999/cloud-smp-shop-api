import os
import json
import random
import string
import asyncio
import aiohttp
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from discord.ext import commands
import discord
import threading
import time

app = Flask(__name__)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_URL = 'https://pterodactyl.file.properties/api/client/servers/1a7ce997'

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
cloud_points = {}  # {user_id: points}
active_otps = {}  # {user_id: {'otp': code, 'expires': datetime}}
POINTS_CHANNEL_ID = 1390794341764567040
CLOUD_POINTS_FILE = 'cloud_points.txt'


# Load items from JSON
def load_items():
    try:
        with open('items.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


ITEMS = load_items()


# Helper functions
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


def parse_cloud_points(content):
    """Parse cloud points from file content"""
    points_data = {}
    for line in content.strip().split('\n'):
        if line.strip():
            try:
                parts = line.split(':')
                if len(parts) == 2:
                    user_id = parts[0].strip()
                    points = int(parts[1].strip())
                    points_data[user_id] = points
            except ValueError:
                continue
    return points_data


def format_cloud_points(points_data):
    """Format cloud points data for file content"""
    lines = []
    for user_id, points in points_data.items():
        lines.append(f"{user_id}:{points}")
    return '\n'.join(lines)


async def download_cloud_points():
    """Download and parse cloud points file from Discord"""
    try:
        channel = bot.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            return {}

        # Find the cloud points file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        content = await attachment.read()
                        return parse_cloud_points(content.decode('utf-8'))
        return {}
    except Exception as e:
        print(f"Error downloading cloud points: {e}")
        return {}


async def upload_cloud_points():
    """Upload cloud points file to Discord"""
    try:
        channel = bot.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            return False

        # Delete existing file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        await message.delete()
                        break

        # Upload new file
        content = format_cloud_points(cloud_points)
        with open(CLOUD_POINTS_FILE, 'w') as f:
            f.write(content)

        with open(CLOUD_POINTS_FILE, 'rb') as f:
            file = discord.File(f, filename=CLOUD_POINTS_FILE)
            await channel.send(file=file)

        os.remove(CLOUD_POINTS_FILE)
        return True
    except Exception as e:
        print(f"Error uploading cloud points: {e}")
        return False


async def send_pterodactyl_command(command):
    """Send command to Pterodactyl panel"""
    try:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }

        data = {'command': command}

        async with aiohttp.ClientSession() as session:
            async with session.post(f'{PTERODACTYL_URL}/command',
                                    json=data, headers=headers) as response:
                return response.status == 204
    except Exception as e:
        print(f"Error sending command to Pterodactyl: {e}")
        return False


# Discord Bot Events
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    # Load cloud points on startup
    global cloud_points
    cloud_points = await download_cloud_points()
    print(f"Loaded {len(cloud_points)} user cloud points")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Add 5 cloud points for each message
    user_id = str(message.author.id)
    if user_id not in cloud_points:
        cloud_points[user_id] = 0
    cloud_points[user_id] += 5

    # Upload updated points (you might want to batch this for performance)
    await upload_cloud_points()

    await bot.process_commands(message)


# Flask API Routes
@app.route('/api/user/<user_id>')
async def get_user_info(user_id):
    try:
        # Get Discord user info
        user = bot.get_user(int(user_id))
        if not user:
            return jsonify({'error': 'User not found'}), 404

        # Get cloud points
        points = cloud_points.get(user_id, 0)

        return jsonify({
            'discord_id': user_id,
            'username': user.display_name,
            'avatar_url': str(user.avatar.url) if user.avatar else str(user.default_avatar.url),
            'cloud_points': points
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm/', methods=['POST'])
async def send_otp_dm(user_id):
    try:
        # Generate OTP
        otp = generate_otp()
        expires = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            'otp': otp,
            'expires': expires
        }

        # Send DM to user
        user = bot.get_user(int(user_id))
        if not user:
            return jsonify({'error': 'User not found'}), 404

        try:
            await user.send(f"🔐 Your OTP for ☁️ Cloud Points Shop: `{otp}`\n⏰ Expires in 5 minutes")
            return jsonify({'message': 'OTP sent successfully'})
        except discord.Forbidden:
            return jsonify({'error': 'Unable to send DM to user'}), 403

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/<otp>/item/<item_number>/<ingame_name>', methods=['POST'])
async def purchase_item(user_id, otp, item_number, ingame_name):
    try:
        # Verify OTP
        if user_id not in active_otps:
            return jsonify({'error': 'No active OTP found'}), 400

        otp_data = active_otps[user_id]
        if otp_data['otp'] != otp:
            return jsonify({'error': 'Invalid OTP'}), 400

        if datetime.now() > otp_data['expires']:
            del active_otps[user_id]
            return jsonify({'error': 'OTP expired'}), 400

        # Check if item exists
        if item_number not in ITEMS:
            return jsonify({'error': 'Item not found'}), 404

        item = ITEMS[item_number]
        item_price = int(item['item-price'])

        # Check if user has enough points
        user_points = cloud_points.get(user_id, 0)
        if user_points < item_price:
            return jsonify({'error': 'Insufficient cloud points'}), 400

        # Deduct points
        cloud_points[user_id] -= item_price

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)
        command_sent = await send_pterodactyl_command(command)

        if not command_sent:
            # Refund points if command failed
            cloud_points[user_id] += item_price
            return jsonify({'error': 'Failed to execute command'}), 500

        # Upload updated points
        await upload_cloud_points()

        # Invalidate OTP
        del active_otps[user_id]

        return jsonify({
            'message': 'Purchase successful',
            'item': item['item-name'],
            'points_deducted': item_price,
            'remaining_points': cloud_points[user_id]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/item-info/<item_number>')
def get_item_info(item_number):
    try:
        if item_number not in ITEMS:
            return jsonify({'error': 'Item not found'}), 404

        item = ITEMS[item_number]
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
    try:
        items_list = []
        for item_number, item_data in ITEMS.items():
            items_list.append({
                'item_number': item_number,
                'item_name': item_data['item-name'],
                'item_price': int(item_data['item-price']),
                'item_icon': item_data['item-icon']
            })
        return jsonify({'items': items_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Function to run Discord bot
def run_discord_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot.run(DISCORD_TOKEN)


# Start Discord bot in a separate thread
if __name__ == '__main__':
    # Start Discord bot in background thread
    bot_thread = threading.Thread(target=run_discord_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Start Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)
else:
    # For production deployment (like Vercel)
    bot_thread = threading.Thread(target=run_discord_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Give bot time to start
    time.sleep(2)