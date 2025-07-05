
from flask import Flask, jsonify, request
import os
import json
import requests
import random
import string
from datetime import datetime, timedelta
import discord
import asyncio
import threading
from bot import get_bot_instance

app = Flask(__name__)

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = "1a7ce997"
PTERODACTYL_BASE_URL = "https://pterodactyl.file.properties/api/client/servers"
CHANNEL_ID = 1390794341764567040

# OTP storage (in production, use Redis or database)
active_otps = {}

# Discord client for API operations
discord_client = None
bot_instance = None


def init_discord_client():
    """Initialize Discord client for API operations"""
    global discord_client
    if not discord_client:
        intents = discord.Intents.default()
        intents.message_content = True
        discord_client = discord.Client(intents=intents)

        @discord_client.event
        async def on_ready():
            print(f'Discord API client ready: {discord_client.user}')

    return discord_client


def run_discord_client():
    """Run Discord client in background"""
    if not discord_client.is_ready():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(discord_client.start(DISCORD_TOKEN))


def load_items():
    """Load items from items.json"""
    try:
        with open('items.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def get_user_from_channel():
    """Get user data from Discord channel file"""
    try:
        if not discord_client or not discord_client.is_ready():
            return {}

        channel = discord_client.get_channel(CHANNEL_ID)
        if not channel:
            return {}

        # This is a simplified version - in practice, you'd need to make this async
        # For now, we'll use the bot instance if available
        if bot_instance:
            return bot_instance.points_data

        return {}
    except Exception as e:
        print(f"Error getting user data: {e}")
        return {}


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
        "discord_connected": discord_client is not None and discord_client.is_ready() if discord_client else False,
        "pterodactyl_configured": bool(PTERODACTYL_API_KEY),
        "active_otps": len(active_otps)
    }
    return jsonify(status)


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Get user data from bot instance or channel
        user_data = {}
        if bot_instance:
            user_data = bot_instance.get_user_points(user_id)

        if not user_data:
            return jsonify({"error": "User not found"}), 404

        # Try to get Discord user info
        discord_user = None
        if discord_client and discord_client.is_ready():
            try:
                discord_user = discord_client.get_user(int(user_id))
            except:
                pass

        response = {
            "user_id": user_id,
            "username": user_data.get("username", "Unknown"),
            "cloud_points": user_data.get("points", 0),
            "messages_sent": user_data.get("messages", 0),
            "last_updated": user_data.get("last_updated", ""),
            "discord_avatar": str(discord_user.avatar.url) if discord_user and discord_user.avatar else None
        }

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<user_id>/send-otp-dm', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        if not discord_client or not discord_client.is_ready():
            return jsonify({"error": "Discord client not ready"}), 503

        # Generate OTP
        otp = generate_otp()
        expires_at = datetime.now() + timedelta(minutes=5)

        # Store OTP
        active_otps[user_id] = {
            "otp": otp,
            "expires_at": expires_at,
            "used": False
        }

        # Send DM (this would need to be async in practice)
        user = discord_client.get_user(int(user_id))
        if not user:
            return jsonify({"error": "User not found"}), 404

        # For now, we'll just return the OTP (in production, actually send DM)
        embed_data = {
            "title": "☁️ Shop Verification Code",
            "description": f"Your verification code is: **{otp}**",
            "color": 0x87CEEB,
            "fields": [
                {"name": "Expires", "value": "5 minutes", "inline": True},
                {"name": "Use Case", "value": "Shop Purchase", "inline": True}
            ],
            "footer": {"text": "Do not share this code with anyone!"}
        }

        return jsonify({
            "success": True,
            "message": "OTP sent to DM",
            "expires_in": 300,
            "otp": otp  # Remove this in production
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
        user_data = {}
        if bot_instance:
            user_data = bot_instance.get_user_points(user_id)

        if not user_data:
            return jsonify({"error": "User not found"}), 404

        user_points = user_data.get("points", 0)
        item_price = int(item["item-price"])

        if user_points < item_price:
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Deduct points
        if bot_instance:
            success = bot_instance.deduct_points(user_id, item_price)
            if not success:
                return jsonify({"error": "Failed to deduct points"}), 500

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)

        if send_pterodactyl_command(command):
            # Mark OTP as used
            active_otps[user_id]["used"] = True

            # Save points data
            if bot_instance:
                asyncio.create_task(bot_instance.save_points_data())

            return jsonify({
                "success": True,
                "message": "Item purchased successfully",
                "item": item["item-name"],
                "price": item_price,
                "remaining_points": user_points - item_price,
                "command_executed": command
            })
        else:
            # Refund points if command failed
            if bot_instance:
                bot_instance.points_data[user_id]["points"] += item_price

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


# Initialize Discord client when app starts
@app.before_first_request
def initialize():
    global bot_instance
    try:
        bot_instance = get_bot_instance()
        init_discord_client()

        # Start Discord client in background thread
        discord_thread = threading.Thread(target=run_discord_client)
        discord_thread.daemon = True
        discord_thread.start()
    except Exception as e:
        print(f"Error initializing: {e}")


if __name__ == '__main__':
    app.run(debug=True, port=5000)
