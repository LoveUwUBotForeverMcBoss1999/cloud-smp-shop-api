import os
import json
import random
import string
import asyncio
import aiohttp
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
import discord

app = Flask(__name__)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_URL = 'https://pterodactyl.file.properties/api/client/servers/1a7ce997'

# Global variables for OTP storage (in production, use Redis or database)
active_otps = {}  # {user_id: {'otp': code, 'expires': datetime}}
POINTS_CHANNEL_ID = 1390794341764567040
CLOUD_POINTS_FILE = 'cloud_points.txt'


# Load items from JSON
def load_items():
    try:
        # Try to load from the same directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        items_path = os.path.join(current_dir, '..', 'items.json')
        if os.path.exists(items_path):
            with open(items_path, 'r') as f:
                return json.load(f)

        # Fallback to inline items
        return {
            "1": {
                "item-name": "Golden Apple",
                "item-price": "100",
                "item-cmd": "give {ingame-name} golden_apple",
                "item-icon": "https://static.wikia.nocookie.net/minecraft_gamepedia/images/5/54/Golden_Apple_JE2_BE2.png/revision/latest?cb=20200521041809"
            },
            "2": {
                "item-name": "Diamond Sword",
                "item-price": "250",
                "item-cmd": "give {ingame-name} diamond_sword",
                "item-icon": "https://static.wikia.nocookie.net/minecraft_gamepedia/images/4/44/Diamond_Sword_JE3_BE3.png/revision/latest?cb=20200217235849"
            },
            "3": {
                "item-name": "Netherite Ingot",
                "item-price": "500",
                "item-cmd": "give {ingame-name} netherite_ingot",
                "item-icon": "https://static.wikia.nocookie.net/minecraft_gamepedia/images/4/41/Netherite_Ingot_JE1_BE1.png/revision/latest?cb=20200217235903"
            }
        }
    except Exception:
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


async def get_discord_client():
    """Get Discord client instance"""
    client = discord.Client(intents=discord.Intents.default())
    await client.login(DISCORD_TOKEN)
    return client


async def download_cloud_points():
    """Download and parse cloud points file from Discord"""
    try:
        client = await get_discord_client()
        channel = client.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            await client.close()
            return {}

        # Find the cloud points file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        content = await attachment.read()
                        await client.close()
                        return parse_cloud_points(content.decode('utf-8'))

        await client.close()
        return {}
    except Exception as e:
        print(f"Error downloading cloud points: {e}")
        return {}


async def upload_cloud_points(points_data):
    """Upload cloud points file to Discord"""
    try:
        client = await get_discord_client()
        channel = client.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            await client.close()
            return False

        # Delete existing file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        await message.delete()
                        break

        # Upload new file
        content = format_cloud_points(points_data)
        with open(f'/tmp/{CLOUD_POINTS_FILE}', 'w') as f:
            f.write(content)

        with open(f'/tmp/{CLOUD_POINTS_FILE}', 'rb') as f:
            file = discord.File(f, filename=CLOUD_POINTS_FILE)
            await channel.send(file=file)

        os.remove(f'/tmp/{CLOUD_POINTS_FILE}')
        await client.close()
        return True
    except Exception as e:
        print(f"Error uploading cloud points: {e}")
        return False


async def send_discord_dm(user_id, message):
    """Send DM to Discord user"""
    try:
        client = await get_discord_client()
        user = await client.fetch_user(int(user_id))
        if not user:
            await client.close()
            return False

        await user.send(message)
        await client.close()
        return True
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False


async def get_discord_user_info(user_id):
    """Get Discord user information"""
    try:
        client = await get_discord_client()
        user = await client.fetch_user(int(user_id))
        if not user:
            await client.close()
            return None

        user_info = {
            'discord_id': str(user.id),
            'username': user.display_name,
            'avatar_url': str(user.avatar.url) if user.avatar else str(user.default_avatar.url)
        }
        await client.close()
        return user_info
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None


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


# Flask API Routes
@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    try:
        # Get Discord user info
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        user_info = loop.run_until_complete(get_discord_user_info(user_id))

        if not user_info:
            return jsonify({'error': 'User not found'}), 404

        # Get cloud points
        cloud_points = loop.run_until_complete(download_cloud_points())
        points = cloud_points.get(user_id, 0)

        user_info['cloud_points'] = points
        return jsonify(user_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
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
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        message = f"🔐 Your OTP for ☁️ Cloud Points Shop: `{otp}`\n⏰ Expires in 5 minutes"
        dm_sent = loop.run_until_complete(send_discord_dm(user_id, message))

        if not dm_sent:
            return jsonify({'error': 'Unable to send DM to user'}), 403

        return jsonify({'message': 'OTP sent successfully'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/<otp>/item/<item_number>/<ingame_name>', methods=['POST'])
def purchase_item(user_id, otp, item_number, ingame_name):
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

        # Get current cloud points
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cloud_points = loop.run_until_complete(download_cloud_points())

        # Check if user has enough points
        user_points = cloud_points.get(user_id, 0)
        if user_points < item_price:
            return jsonify({'error': 'Insufficient cloud points'}), 400

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)
        command_sent = loop.run_until_complete(send_pterodactyl_command(command))

        if not command_sent:
            return jsonify({'error': 'Failed to execute command'}), 500

        # Deduct points and upload
        cloud_points[user_id] -= item_price
        upload_success = loop.run_until_complete(upload_cloud_points(cloud_points))

        if not upload_success:
            return jsonify({'error': 'Failed to update points'}), 500

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


# Health check endpoint
@app.route('/api/health')
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Cloud Points API is running'})


# For Vercel
def handler(request):
    return app(request.environ, lambda *args: None)