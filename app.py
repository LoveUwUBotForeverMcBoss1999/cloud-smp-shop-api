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
import requests

app = Flask(__name__)
CORS(app)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_BASE_URL = "https://pterodactyl.file.properties/api/client"
SERVER_ID = "1a7ce997"

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


# Discord HTTP API functions (no bot needed!)
def get_discord_headers():
    return {
        'Authorization': f'Bot {DISCORD_TOKEN}',
        'Content-Type': 'application/json'
    }


def get_user_info_from_discord(user_id):
    """Get user info using Discord HTTP API"""
    try:
        url = f"https://discord.com/api/v10/users/{user_id}"
        response = requests.get(url, headers=get_discord_headers())
        if response.status_code == 200:
            user_data = response.json()
            avatar_url = None
            if user_data.get('avatar'):
                avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{user_data['avatar']}.png"
            return {
                'username': user_data.get('username', 'Unknown'),
                'avatar': avatar_url
            }
    except Exception as e:
        print(f"Error getting user info: {e}")
    return None


def send_dm_to_user(user_id, embed_data):
    """Send DM using Discord HTTP API"""
    try:
        # Create DM channel
        dm_url = "https://discord.com/api/v10/users/@me/channels"
        dm_data = {"recipient_id": str(user_id)}
        dm_response = requests.post(dm_url, headers=get_discord_headers(), json=dm_data)

        if dm_response.status_code == 200:
            dm_channel = dm_response.json()
            channel_id = dm_channel['id']

            # Send message
            message_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            message_data = {"embeds": [embed_data]}
            message_response = requests.post(message_url, headers=get_discord_headers(), json=message_data)

            return message_response.status_code == 200
    except Exception as e:
        print(f"Error sending DM: {e}")
    return False


def get_channel_messages(channel_id, limit=100):
    """Get messages from channel using Discord HTTP API"""
    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit={limit}"
        response = requests.get(url, headers=get_discord_headers())
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error getting messages: {e}")
    return []


def upload_file_to_channel(channel_id, file_content, filename, message_content):
    """Upload file to Discord channel using HTTP API"""
    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

        files = {
            'files[0]': (filename, file_content, 'text/plain')
        }
        data = {
            'content': message_content
        }

        # Remove Content-Type header for multipart
        headers = {'Authorization': f'Bot {DISCORD_TOKEN}'}

        response = requests.post(url, headers=headers, files=files, data=data)
        return response.status_code == 200
    except Exception as e:
        print(f"Error uploading file: {e}")
    return False


def download_attachment(attachment_url):
    """Download attachment content"""
    try:
        response = requests.get(attachment_url)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"Error downloading attachment: {e}")
    return None


class CloudPointsManager:
    def __init__(self):
        self.points_data = {}
        self.last_update = {}
        self.loaded = False

    def load_points_from_discord(self):
        """Load points data from Discord channel"""
        try:
            messages = get_channel_messages(CHANNEL_ID)

            for message in messages:
                if message.get('attachments'):
                    for attachment in message['attachments']:
                        if attachment['filename'] == CLOUD_POINTS_FILE:
                            content = download_attachment(attachment['url'])
                            if content:
                                self.parse_points_data(content)
                                self.loaded = True
                                return

            # If no file exists, create initial file
            self.create_initial_points_file()

        except Exception as e:
            print(f"Error loading points from Discord: {e}")

    def parse_points_data(self, content):
        """Parse points data from file content"""
        try:
            lines = content.strip().split('\n')
            for line in lines:
                if ':' in line and not line.startswith('#'):
                    user_id, points = line.split(':', 1)
                    self.points_data[user_id.strip()] = int(points.strip())
        except Exception as e:
            print(f"Error parsing points data: {e}")

    def create_initial_points_file(self):
        """Create initial points file in Discord channel"""
        try:
            initial_content = "# Cloud Points Data\n# Format: user_id:points\n"
            success = upload_file_to_channel(
                CHANNEL_ID,
                initial_content,
                CLOUD_POINTS_FILE,
                "☁️ Cloud Points system initialized!"
            )
            if success:
                self.loaded = True
                print("Initial points file created")
        except Exception as e:
            print(f"Error creating initial points file: {e}")

    def update_points_file(self, user_id, points_to_add):
        """Update points file in Discord channel"""
        try:
            if not self.loaded:
                self.load_points_from_discord()

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
            success = upload_file_to_channel(
                CHANNEL_ID,
                content,
                CLOUD_POINTS_FILE,
                f"☁️ Points updated! User {user_id} now has {new_points} Cloud Points"
            )

            if success:
                print(f"Points updated for user {user_id}: {new_points}")

            return new_points

        except Exception as e:
            print(f"Error updating points file: {e}")
            return self.points_data.get(user_id, 0)

    def get_points(self, user_id):
        """Get current points for a user"""
        if not self.loaded:
            self.load_points_from_discord()
        return self.points_data.get(str(user_id), 0)

    def deduct_points(self, user_id, points_to_deduct):
        """Deduct points from user"""
        user_id = str(user_id)
        current_points = self.get_points(user_id)
        if current_points >= points_to_deduct:
            self.points_data[user_id] = current_points - points_to_deduct

            # Update file immediately for purchases
            content = "# Cloud Points Data\n# Format: user_id:points\n"
            for uid, points in self.points_data.items():
                content += f"{uid}:{points}\n"

            upload_file_to_channel(
                CHANNEL_ID,
                content,
                CLOUD_POINTS_FILE,
                f"☁️ Purchase completed! User {user_id} spent {points_to_deduct} points"
            )

            return True
        return False


points_manager = CloudPointsManager()


def generate_otp():
    """Generate a random 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


def send_command_to_pterodactyl(command):
    """Send command to Pterodactyl panel"""
    try:
        url = f"{PTERODACTYL_BASE_URL}/servers/{SERVER_ID}/command"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }
        data = {'command': command}

        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 204
    except Exception as e:
        print(f"Error sending command to Pterodactyl: {e}")
        return False


# Flask API Routes

@app.route('/')
def health_check():
    """Health check endpoint"""
    try:
        # Test Discord API connection
        test_url = "https://discord.com/api/v10/users/@me"
        response = requests.get(test_url, headers=get_discord_headers())
        discord_status = "online" if response.status_code == 200 else "offline"

        return jsonify({
            'status': 'healthy',
            'discord_api_status': discord_status,
            'points_system_loaded': points_manager.loaded,
            'message': '☁️ Cloud Points API is running!'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'discord_api_status': 'offline',
            'error': str(e)
        })


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Get user info from Discord
        discord_user = get_user_info_from_discord(user_id)
        points = points_manager.get_points(user_id)

        if discord_user:
            return jsonify({
                'username': discord_user['username'],
                'avatar': discord_user['avatar'],
                'points': points
            })
        else:
            return jsonify({
                'username': 'Unknown User',
                'avatar': None,
                'points': points
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/award-points/<user_id>', methods=['POST'])
def award_points(user_id):
    """Award points to user (for webhook integration)"""
    try:
        new_points = points_manager.update_points_file(user_id, POINTS_PER_MESSAGE)

        # Cache user data
        discord_user = get_user_info_from_discord(user_id)
        if discord_user:
            user_data_cache[user_id] = {
                'username': discord_user['username'],
                'avatar': discord_user['avatar'],
                'points': new_points
            }

        return jsonify({
            'success': True,
            'points_awarded': POINTS_PER_MESSAGE,
            'total_points': new_points
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        # Generate OTP
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            'otp': otp,
            'expiry': expiry,
            'used': False
        }

        # Create embed
        embed_data = {
            "title": "☁️ Cloud Points Shop - OTP Verification",
            "description": f"Your OTP code: **{otp}**",
            "color": 0x00ff00,
            "fields": [
                {"name": "Expires in", "value": "5 minutes", "inline": False},
                {"name": "Note", "value": "This code can only be used once!", "inline": False}
            ]
        }

        # Send DM
        success = send_dm_to_user(user_id, embed_data)

        if success:
            return jsonify({
                'success': True,
                'message': 'OTP sent to DM',
                'expires_in': '5 minutes'
            })
        else:
            return jsonify({'error': 'Failed to send DM'}), 500

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
        if not points_manager.deduct_points(user_id, item_price):
            return jsonify({'error': 'Failed to deduct points'}), 500

        # Mark OTP as used
        active_otps[user_id]['used'] = True

        # Send command to Pterodactyl
        command = item['item-cmd'].replace('{ingame-name}', ingame_name)
        command_success = send_command_to_pterodactyl(command)

        # Send confirmation DM
        embed_data = {
            "title": "☁️ Purchase Successful!",
            "description": f"You have successfully purchased **{item['item-name']}**",
            "color": 0x00ff00,
            "fields": [
                {"name": "In-game Name", "value": ingame_name, "inline": True},
                {"name": "Status", "value": "✅ Delivered" if command_success else "❌ Failed", "inline": True},
                {"name": "Points Spent", "value": str(item_price), "inline": True}
            ]
        }

        send_dm_to_user(user_id, embed_data)

        return jsonify({
            'success': True,
            'message': f'Successfully purchased {item["item-name"]}',
            'item': item['item-name'],
            'points_remaining': user_points - item_price,
            'delivery_status': 'delivered' if command_success else 'failed'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


# Initialize points system on startup
@app.before_first_request
def initialize_points_system():
    """Initialize the points system when the app starts"""
    try:
        points_manager.load_points_from_discord()
        print("Points system initialized successfully")
    except Exception as e:
        print(f"Error initializing points system: {e}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)