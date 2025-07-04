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


def download_cloud_points():
    """Download and parse cloud points file from Discord using REST API"""
    try:
        headers = {
            'Authorization': f'Bot {DISCORD_TOKEN}',
            'Content-Type': 'application/json'
        }

        # Get recent messages from the channel
        response = requests.get(
            f'https://discord.com/api/v10/channels/{POINTS_CHANNEL_ID}/messages?limit=100',
            headers=headers
        )

        if response.status_code != 200:
            print(f"Error getting messages: {response.status_code}")
            return {}

        messages = response.json()

        # Find the cloud points file
        for message in messages:
            if message.get('attachments'):
                for attachment in message['attachments']:
                    if attachment['filename'] == CLOUD_POINTS_FILE:
                        # Download the file
                        file_response = requests.get(attachment['url'])
                        if file_response.status_code == 200:
                            return parse_cloud_points(file_response.text)

        return {}
    except Exception as e:
        print(f"Error downloading cloud points: {e}")
        return {}


def upload_cloud_points(points_data):
    """Upload cloud points file to Discord using REST API"""
    try:
        headers = {
            'Authorization': f'Bot {DISCORD_TOKEN}'
        }

        # First, delete existing file message
        response = requests.get(
            f'https://discord.com/api/v10/channels/{POINTS_CHANNEL_ID}/messages?limit=100',
            headers={'Authorization': f'Bot {DISCORD_TOKEN}', 'Content-Type': 'application/json'}
        )

        if response.status_code == 200:
            messages = response.json()
            for message in messages:
                if message.get('attachments'):
                    for attachment in message['attachments']:
                        if attachment['filename'] == CLOUD_POINTS_FILE:
                            # Delete the message
                            requests.delete(
                                f'https://discord.com/api/v10/channels/{POINTS_CHANNEL_ID}/messages/{message["id"]}',
                                headers={'Authorization': f'Bot {DISCORD_TOKEN}'}
                            )
                            break

        # Upload new file
        content = format_cloud_points(points_data)
        files = {
            'file': (CLOUD_POINTS_FILE, content, 'text/plain')
        }

        response = requests.post(
            f'https://discord.com/api/v10/channels/{POINTS_CHANNEL_ID}/messages',
            headers=headers,
            files=files
        )

        return response.status_code == 200
    except Exception as e:
        print(f"Error uploading cloud points: {e}")
        return False


def send_discord_dm(user_id, message):
    """Send DM to Discord user using REST API"""
    try:
        headers = {
            'Authorization': f'Bot {DISCORD_TOKEN}',
            'Content-Type': 'application/json'
        }

        # Create DM channel
        dm_response = requests.post(
            'https://discord.com/api/v10/users/@me/channels',
            headers=headers,
            json={'recipient_id': user_id}
        )

        if dm_response.status_code != 200:
            return False

        dm_channel = dm_response.json()

        # Send message
        msg_response = requests.post(
            f'https://discord.com/api/v10/channels/{dm_channel["id"]}/messages',
            headers=headers,
            json={'content': message}
        )

        return msg_response.status_code == 200
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False


def get_discord_user_info(user_id):
    """Get Discord user information using REST API"""
    try:
        headers = {
            'Authorization': f'Bot {DISCORD_TOKEN}',
            'Content-Type': 'application/json'
        }

        response = requests.get(
            f'https://discord.com/api/v10/users/{user_id}',
            headers=headers
        )

        if response.status_code != 200:
            return None

        user_data = response.json()

        # Build avatar URL
        avatar_url = f'https://cdn.discordapp.com/embed/avatars/{int(user_data["discriminator"]) % 5}.png'
        if user_data.get('avatar'):
            avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{user_data["avatar"]}.png'

        return {
            'discord_id': user_id,
            'username': user_data.get('global_name') or user_data.get('username', 'Unknown'),
            'avatar_url': avatar_url
        }
    except Exception as e:
        print(f"Error getting user info: {e}")
        return None


def send_pterodactyl_command(command):
    """Send command to Pterodactyl panel"""
    try:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }

        data = {'command': command}

        response = requests.post(f'{PTERODACTYL_URL}/command',
                                 json=data, headers=headers, timeout=10)
        return response.status_code == 204
    except Exception as e:
        print(f"Error sending command to Pterodactyl: {e}")
        return False


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    try:
        # Get Discord user info
        user_info = get_discord_user_info(user_id)

        if not user_info:
            return jsonify({'error': 'User not found'}), 404

        # Get cloud points
        cloud_points = download_cloud_points()
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
        message = f"🔐 Your OTP for ☁️ Cloud Points Shop: `{otp}`\n⏰ Expires in 5 minutes"
        dm_sent = send_discord_dm(user_id, message)

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
        cloud_points = download_cloud_points()

        # Check if user has enough points
        user_points = cloud_points.get(user_id, 0)
        if user_points < item_price:
            return jsonify({'error': 'Insufficient cloud points'}), 400

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)
        command_sent = send_pterodactyl_command(command)

        if not command_sent:
            return jsonify({'error': 'Failed to execute command'}), 500

        # Deduct points and upload
        cloud_points[user_id] -= item_price
        upload_success = upload_cloud_points(cloud_points)

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