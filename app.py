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

app = Flask(__name__)
CORS(app)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = os.getenv('PTERODACTYL_SERVER_ID', '1a7ce997')
PTERODACTYL_BASE_URL = os.getenv('PTERODACTYL_BASE_URL', 'https://pterodactyl.file.properties')

# Storage for OTPs (in production, use Redis or database)
otps = {}

# Channel ID where cloud_points.txt is stored
CLOUD_POINTS_CHANNEL_ID = 1390794341764567040

# Discord client for API calls only
intents = discord.Intents.default()
intents.message_content = True


async def get_discord_client():
    """Get Discord client for API calls"""
    client = discord.Client(intents=intents)
    await client.login(DISCORD_TOKEN)
    return client


async def load_points_from_discord():
    """Load points from Discord channel"""
    try:
        client = await get_discord_client()
        channel = client.get_channel(CLOUD_POINTS_CHANNEL_ID)

        if not channel:
            await client.close()
            return {}

        # Look for existing cloud_points.txt
        async for message in channel.history(limit=50):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == 'cloud_points.txt':
                        content = await attachment.read()
                        await client.close()
                        return json.loads(content.decode('utf-8'))

        await client.close()
        return {}

    except Exception as e:
        print(f"Error loading points: {e}")
        return {}


async def get_discord_user_info(user_id):
    """Get Discord user info"""
    try:
        client = await get_discord_client()
        user = await client.fetch_user(user_id)

        user_info = {
            "username": user.name,
            "avatar": str(user.avatar.url) if user.avatar else str(user.default_avatar.url)
        }

        await client.close()
        return user_info

    except Exception as e:
        print(f"Error getting user info: {e}")
        return None


async def send_dm_to_user(user_id, message):
    """Send DM to Discord user"""
    try:
        client = await get_discord_client()
        user = await client.fetch_user(user_id)
        await user.send(message)
        await client.close()
        return True

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
    return jsonify({
        "status": "healthy",
        "service": "Cloud Points API",
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/user/<int:user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Get user info from Discord
        user_info = asyncio.run(get_discord_user_info(user_id))
        if not user_info:
            return jsonify({"error": "User not found"}), 404

        # Get points from Discord file
        points_data = asyncio.run(load_points_from_discord())
        points = points_data.get(str(user_id), 0)

        return jsonify({
            "discord_id": user_id,
            "username": user_info["username"],
            "avatar": user_info["avatar"],
            "cloud_points": points
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<int:user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Store OTP with expiry
        otps[user_id] = {
            "code": otp,
            "expiry": expiry,
            "used": False
        }

        # Send DM
        message = f"🔐 Your OTP code for ☁️ Cloud Points shop: **{otp}**\n\nThis code expires in 5 minutes."
        success = asyncio.run(send_dm_to_user(user_id, message))

        if not success:
            return jsonify({"error": "Failed to send DM"}), 500

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

        # Get current points
        points_data = asyncio.run(load_points_from_discord())
        user_points = points_data.get(str(user_id), 0)

        # Check if user has enough points
        if user_points < item_price:
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Execute item command first
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)
        command_success = asyncio.run(send_pterodactyl_command(command))

        if not command_success:
            return jsonify({"error": "Failed to execute item command"}), 500

        # Mark OTP as used
        otps[user_id]["used"] = True

        # Note: Points deduction would need to be handled by the Discord bot
        # For now, we'll return success but mention points need manual deduction

        return jsonify({
            "success": True,
            "message": f"Successfully purchased {item['item-name']}",
            "item": item["item-name"],
            "cost": item_price,
            "note": "Points will be deducted by the Discord bot"
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


# For Vercel
def handler(request):
    return app(request.environ, lambda *args: None)


if __name__ == '__main__':
    app.run(debug=True)