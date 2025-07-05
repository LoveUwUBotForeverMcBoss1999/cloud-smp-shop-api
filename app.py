from flask import Flask, jsonify, request
import os
import json
import requests
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = "1a7ce997"
PTERODACTYL_BASE_URL = "https://pterodactyl.file.properties/api/client/servers"
CHANNEL_ID = 1390794341764567040
DISCORD_API_BASE = "https://discord.com/api/v10"

# OTP storage (in production, use Redis or database)
active_otps = {}

# In-memory points storage for API (will be replaced by reading from Discord)
points_cache = {}


def get_discord_headers():
    """Get Discord API headers"""
    return {
        'Authorization': f'Bot {DISCORD_TOKEN}',
        'Content-Type': 'application/json'
    }


def get_user_data_from_discord():
    """Fetch user data from Discord channel messages"""
    try:
        headers = get_discord_headers()
        url = f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}/messages"

        response = requests.get(url, headers=headers, params={'limit': 100})

        if response.status_code != 200:
            print(f"Discord API error: {response.status_code}")
            return {}

        messages = response.json()

        # Look for the cloud_points.txt file
        for message in messages:
            if message.get('attachments'):
                for attachment in message['attachments']:
                    if attachment['filename'] == 'cloud_points.txt':
                        # Download the file
                        file_response = requests.get(attachment['url'])
                        if file_response.status_code == 200:
                            try:
                                return json.loads(file_response.text)
                            except json.JSONDecodeError:
                                continue

        return {}
    except Exception as e:
        print(f"Error fetching Discord data: {e}")
        return {}


def get_discord_user_info(user_id):
    """Get Discord user info via API"""
    try:
        headers = get_discord_headers()
        url = f"{DISCORD_API_BASE}/users/{user_id}"

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Error getting Discord user: {e}")
        return None


def send_discord_dm(user_id, embed_data):
    """Send DM to Discord user"""
    try:
        headers = get_discord_headers()

        # Create DM channel
        dm_url = f"{DISCORD_API_BASE}/users/@me/channels"
        dm_data = {'recipient_id': user_id}

        dm_response = requests.post(dm_url, headers=headers, json=dm_data)

        if dm_response.status_code == 200:
            dm_channel = dm_response.json()

            # Send message to DM channel
            message_url = f"{DISCORD_API_BASE}/channels/{dm_channel['id']}/messages"
            message_data = {'embeds': [embed_data]}

            message_response = requests.post(message_url, headers=headers, json=message_data)
            return message_response.status_code == 200

        return False
    except Exception as e:
        print(f"Error sending DM: {e}")
        return False


def load_items():
    """Load items from items.json"""
    try:
        with open('items.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_user_from_channel():
    """Get user data from Discord channel file"""
    global points_cache

    try:
        # Try to get fresh data from Discord
        discord_data = get_user_data_from_discord()
        if discord_data:
            points_cache = discord_data
            return discord_data

        # Fallback to cache if Discord fetch fails
        return points_cache

    except Exception as e:
        print(f"Error getting user data: {e}")
        return points_cache


def generate_otp():
    """Generate 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


def send_pterodactyl_command(command):
    """Send command to Pterodactyl server"""
    try:
        url = f"{PTERODACTYL_BASE_URL}/{PTERODACTYL_SERVER_ID}/command"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }
        data = {'command': command}

        response = requests.post(url, headers=headers, json=data)
        return response.status_code == 204
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


@app.route('/')
def health_check():
    """Health check endpoint"""
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "discord_token_configured": bool(DISCORD_TOKEN),
        "pterodactyl_configured": bool(PTERODACTYL_API_KEY),
        "active_otps": len(active_otps),
        "cached_users": len(points_cache)
    }
    return jsonify(status)


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Get user data from Discord channel
        all_user_data = get_user_from_channel()
        user_data = all_user_data.get(str(user_id), {})

        if not user_data:
            return jsonify({"error": "User not found"}), 404

        # Get Discord user info
        discord_user = get_discord_user_info(user_id)

        avatar_url = None
        if discord_user and discord_user.get('avatar'):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{discord_user['avatar']}.png"

        response = {
            "user_id": user_id,
            "username": user_data.get("username",
                                      discord_user.get("username", "Unknown") if discord_user else "Unknown"),
            "cloud_points": user_data.get("points", 0),
            "messages_sent": user_data.get("messages", 0),
            "last_updated": user_data.get("last_updated", ""),
            "discord_avatar": avatar_url
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        # Generate OTP
        otp = generate_otp()
        expires_at = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            "otp": otp,
            "expires_at": expires_at,
            "used": False
        }

        # Create embed for DM
        embed_data = {
            "title": "☁️ Shop Verification Code",
            "description": f"Your verification code is: **{otp}**",
            "color": 0x87CEEB,
            "fields": [
                {"name": "Expires", "value": "5 minutes", "inline": True},
                {"name": "Use Case", "value": "Shop Purchase", "inline": True}
            ],
            "footer": {"text": "Do not share this code with anyone!"},
            "timestamp": datetime.now().isoformat()
        }

        # Send DM
        dm_sent = send_discord_dm(user_id, embed_data)

        if dm_sent:
            return jsonify({
                "success": True,
                "message": "OTP sent to DM",
                "expires_in": 300
            })
        else:
            return jsonify({
                "success": False,
                "message": "Failed to send DM, but OTP is generated",
                "expires_in": 300,
                "otp": otp  # Include OTP if DM fails
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<user_id>/<otp>/item/<item_number>/<ingame_name>', methods=['POST'])
def purchase_item(user_id, otp, item_number, ingame_name):
    """Purchase item using OTP verification"""
    try:
        # Verify OTP
        if user_id not in active_otps:
            return jsonify({"error": "No OTP found"}), 400

        otp_data = active_otps[user_id]

        if otp_data["used"]:
            return jsonify({"error": "OTP already used"}), 400

        if datetime.now() > otp_data["expires_at"]:
            del active_otps[user_id]
            return jsonify({"error": "OTP expired"}), 400

        if otp_data["otp"] != otp:
            return jsonify({"error": "Invalid OTP"}), 400

        # Load items
        items = load_items()
        if item_number not in items:
            return jsonify({"error": "Item not found"}), 404

        item = items[item_number]

        # Check user points
        all_user_data = get_user_from_channel()
        user_data = all_user_data.get(str(user_id), {})

        if not user_data:
            return jsonify({"error": "User not found"}), 404

        user_points = user_data.get("points", 0)
        item_price = int(item["item-price"])

        if user_points < item_price:
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)

        if send_pterodactyl_command(command):
            # Mark OTP as used
            active_otps[user_id]["used"] = True

            # Note: Points deduction would need to be handled by the bot
            # For now, we'll just return success

            return jsonify({
                "success": True,
                "message": "Item purchased successfully",
                "item": item["item-name"],
                "price": item_price,
                "remaining_points": user_points - item_price,
                "command_executed": command,
                "note": "Points will be deducted by the bot system"
            })
        else:
            return jsonify({"error": "Failed to execute item command"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/item-info/<item_number>')
def get_item_info(item_number):
    """Get item information"""
    try:
        items = load_items()

        if item_number not in items:
            return jsonify({"error": "Item not found"}), 404

        item = items[item_number]

        return jsonify({
            "item_id": item_number,
            "item_name": item["item-name"],
            "item_price": int(item["item-price"]),
            "item_icon": item["item-icon"],
            "item_command": item["item-cmd"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/items')
def get_all_items():
    """Get all shop items"""
    try:
        items = load_items()

        formatted_items = []
        for item_id, item_data in items.items():
            formatted_items.append({
                "item_id": item_id,
                "item_name": item_data["item-name"],
                "item_price": int(item_data["item-price"]),
                "item_icon": item_data["item-icon"]
            })

        return jsonify({
            "items": formatted_items,
            "total_items": len(formatted_items)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)