import os
import json
import random
import string
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

app = Flask(__name__)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_URL = 'https://pterodactyl.file.properties/api/client/servers/1a7ce997'

# Discord API endpoints
DISCORD_API_BASE = 'https://discord.com/api/v10'
POINTS_CHANNEL_ID = 1390794341764567040
CLOUD_POINTS_FILE = 'cloud_points.txt'

# In-memory storage for OTPs (use Redis in production)
active_otps = {}


# Load items
def load_items():
    items = {
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
        },
        "4": {
            "item-name": "Enchanted Book (Mending)",
            "item-price": "300",
            "item-cmd": "give {ingame-name} enchanted_book{StoredEnchantments:[{id:mending,lvl:1}]}",
            "item-icon": "https://static.wikia.nocookie.net/minecraft_gamepedia/images/c/ca/Enchanted_Book_JE2_BE2.png/revision/latest?cb=20200217235836"
        },
        "5": {
            "item-name": "Elytra",
            "item-price": "1000",
            "item-cmd": "give {ingame-name} elytra",
            "item-icon": "https://static.wikia.nocookie.net/minecraft_gamepedia/images/3/32/Elytra_JE2_BE2.png/revision/latest?cb=20200217235838"
        }
    }
    return items


ITEMS = load_items()


# Helper functions
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


def discord_headers():
    return {
        'Authorization': f'Bot {DISCORD_TOKEN}',
        'Content-Type': 'application/json'
    }


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


def get_discord_user_info(user_id):
    """Get Discord user information using REST API"""
    try:
        response = requests.get(
            f'{DISCORD_API_BASE}/users/{user_id}',
            headers=discord_headers(),
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            avatar_hash = user_data.get('avatar')
            if avatar_hash:
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
            else:
                discriminator = user_data.get('discriminator', '0000')
                if discriminator == '0' or discriminator == '0000':
                    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
                else:
                    avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(discriminator) % 5}.png"

            return {
                'discord_id': user_id,
                'username': user_data.get('username', 'Unknown'),
                'display_name': user_data.get('global_name') or user_data.get('username', 'Unknown'),
                'avatar_url': avatar_url
            }
        return None
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None


def send_discord_dm(user_id, message):
    """Send DM to Discord user using REST API"""
    try:
        # Create DM channel
        dm_response = requests.post(
            f'{DISCORD_API_BASE}/users/@me/channels',
            headers=discord_headers(),
            json={'recipient_id': user_id},
            timeout=10
        )

        if dm_response.status_code != 200:
            return False

        dm_channel = dm_response.json()
        channel_id = dm_channel['id']

        # Send message
        message_response = requests.post(
            f'{DISCORD_API_BASE}/channels/{channel_id}/messages',
            headers=discord_headers(),
            json={'content': message},
            timeout=10
        )

        return message_response.status_code == 200
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False


def get_cloud_points_from_channel():
    """Get cloud points from Discord channel"""
    try:
        response = requests.get(
            f'{DISCORD_API_BASE}/channels/{POINTS_CHANNEL_ID}/messages',
            headers=discord_headers(),
            params={'limit': 100},
            timeout=10
        )

        if response.status_code != 200:
            return {}

        messages = response.json()
        for message in messages:
            if message.get('attachments'):
                for attachment in message['attachments']:
                    if attachment['filename'] == CLOUD_POINTS_FILE:
                        file_response = requests.get(attachment['url'], timeout=10)
                        if file_response.status_code == 200:
                            return parse_cloud_points(file_response.text)
        return {}
    except Exception as e:
        print(f"Error getting cloud points: {e}")
        return {}


def send_pterodactyl_command(command):
    """Send command to Pterodactyl panel"""
    try:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }

        response = requests.post(
            f'{PTERODACTYL_URL}/command',
            json={'command': command},
            headers=headers,
            timeout=15
        )

        return response.status_code == 204
    except Exception as e:
        print(f"Error sending command to Pterodactyl: {e}")
        return False


# Routes
@app.route('/')
def home():
    """Root route to verify API is working"""
    return jsonify({
        'status': 'SUCCESS',
        'message': '☁️ Cloud Points API is WORKING!',
        'version': '1.0.0',
        'endpoints': {
            'user_info': '/api/user/{user_id}',
            'send_otp': '/api/shop/{user_id}/send-otp-dm/',
            'purchase': '/api/shop/{user_id}/{otp}/item/{item_number}/{ingame_name}',
            'item_info': '/api/item-info/{item_number}',
            'all_items': '/api/shop/items'
        },
        'working': True
    })


@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'API is working perfectly!',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information and cloud points"""
    try:
        # Get Discord user info
        user_info = get_discord_user_info(user_id)
        if not user_info:
            return jsonify({'error': 'User not found'}), 404

        # Get cloud points
        cloud_points = get_cloud_points_from_channel()
        points = cloud_points.get(user_id, 0)

        user_info['cloud_points'] = points
        return jsonify(user_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        # Generate OTP
        otp = generate_otp()
        expires = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            'otp': otp,
            'expires': expires
        }

        # Send DM
        message = f"🔐 Your OTP for ☁️ Cloud Points Shop: `{otp}`\n⏰ Expires in 5 minutes"
        dm_sent = send_discord_dm(user_id, message)

        if not dm_sent:
            return jsonify({'error': 'Unable to send DM to user'}), 403

        return jsonify({
            'message': 'OTP sent successfully',
            'expires_in': '5 minutes'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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

        if datetime.now() > otp_data['expires']:
            del active_otps[user_id]
            return jsonify({'error': 'OTP expired'}), 400

        # Check if item exists
        if item_number not in ITEMS:
            return jsonify({'error': 'Item not found'}), 404

        item = ITEMS[item_number]
        item_price = int(item['item-price'])

        # Get current cloud points
        cloud_points = get_cloud_points_from_channel()
        user_points = cloud_points.get(user_id, 0)

        if user_points < item_price:
            return jsonify({'error': 'Insufficient cloud points'}), 400

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)
        command_sent = send_pterodactyl_command(command)

        if not command_sent:
            return jsonify({'error': 'Failed to execute command on server'}), 500

        # For now, return success (bot will handle point deduction)
        # In production, you'd want to update the points file here

        # Invalidate OTP
        del active_otps[user_id]

        return jsonify({
            'message': 'Purchase successful!',
            'item': item['item-name'],
            'points_deducted': item_price,
            'command_executed': command,
            'success': True
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/item-info/<item_number>')
def get_item_info(item_number):
    """Get item information"""
    try:
        if item_number not in ITEMS:
            return jsonify({'error': 'Item not found'}), 404

        item = ITEMS[item_number]
        return jsonify({
            'item_number': item_number,
            'item_name': item['item-name'],
            'item_price': int(item['item-price']),
            'item_icon': item['item-icon'],
            'item_cmd': item['item-cmd']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/items')
def get_all_items():
    """Get all shop items"""
    try:
        items_list = []
        for item_number, item_data in ITEMS.items():
            items_list.append({
                'item_number': item_number,
                'item_name': item_data['item-name'],
                'item_price': int(item_data['item-price']),
                'item_icon': item_data['item-icon']
            })
        return jsonify({
            'items': items_list,
            'total_items': len(items_list)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# For Vercel
def handler(event, context):
    return app(event, context)


if __name__ == '__main__':
    app.run(debug=True)