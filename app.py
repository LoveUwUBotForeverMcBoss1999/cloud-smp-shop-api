import os
import json
import random
import string
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Environment variables
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = os.getenv('PTERODACTYL_SERVER_ID', '1a7ce997')
PTERODACTYL_BASE_URL = os.getenv('PTERODACTYL_BASE_URL', 'https://pterodactyl.file.properties')

# Storage for OTPs and user data (in production, use Redis or database)
otps = {}
user_data = {}


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


def send_pterodactyl_command(command):
    """Send command to Pterodactyl panel"""
    try:
        url = f"{PTERODACTYL_BASE_URL}/api/client/servers/{PTERODACTYL_SERVER_ID}/command"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}'
        }
        data = {'command': command}

        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.status_code == 204
    except Exception as e:
        print(f"Error sending command: {e}")
        return False


# Mock user data for testing (replace with actual Discord integration)
def get_mock_user_data(user_id):
    """Get mock user data for testing"""
    if str(user_id) not in user_data:
        user_data[str(user_id)] = {
            "username": f"User{user_id}",
            "avatar": "https://cdn.discordapp.com/embed/avatars/0.png",
            "cloud_points": 500  # Starting points for testing
        }
    return user_data[str(user_id)]


# Flask API Routes

@app.route('/')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Cloud Points API",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    })


@app.route('/api/test')
def test_endpoint():
    """Test endpoint to verify API is working"""
    return jsonify({
        "message": "API is working!",
        "endpoints": [
            "/api/user/{user_id}",
            "/api/shop/{user_id}/send-otp-dm/",
            "/api/shop/{user_id}/{otp}/item/{item_number}/{ingame_name}",
            "/api/item-info/{item_number}",
            "/api/shop/items"
        ]
    })


@app.route('/api/user/<int:user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # For now, use mock data. Replace with actual Discord API calls when Discord bot is running
        user_info = get_mock_user_data(user_id)

        return jsonify({
            "discord_id": user_id,
            "username": user_info["username"],
            "avatar": user_info["avatar"],
            "cloud_points": user_info["cloud_points"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/shop/<int:user_id>/send-otp-dm/', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM (mock for now)"""
    try:
        otp = generate_otp()
        expiry = datetime.now() + timedelta(minutes=5)

        # Store OTP with expiry
        otps[user_id] = {
            "code": otp,
            "expiry": expiry,
            "used": False
        }

        # For now, return OTP in response (for testing)
        # In production, this would send via Discord DM
        return jsonify({
            "success": True,
            "message": "OTP generated successfully",
            "otp": otp,  # Remove this in production
            "expires_at": expiry.isoformat(),
            "note": "In production, this OTP would be sent via Discord DM"
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

        # Get current user data
        user_info = get_mock_user_data(user_id)
        user_points = user_info["cloud_points"]

        # Check if user has enough points
        if user_points < item_price:
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)
        command_success = send_pterodactyl_command(command)

        if not command_success:
            return jsonify({"error": "Failed to execute item command"}), 500

        # Deduct points
        user_data[str(user_id)]["cloud_points"] -= item_price

        # Mark OTP as used
        otps[user_id]["used"] = True

        return jsonify({
            "success": True,
            "message": f"Successfully purchased {item['item-name']}",
            "item": item["item-name"],
            "cost": item_price,
            "remaining_points": user_data[str(user_id)]["cloud_points"],
            "command_executed": command
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


# Admin endpoints for testing
@app.route('/api/admin/add-points/<int:user_id>/<int:points>', methods=['POST'])
def add_points_admin(user_id, points):
    """Add points to user (for testing)"""
    try:
        user_info = get_mock_user_data(user_id)
        user_data[str(user_id)]["cloud_points"] += points

        return jsonify({
            "success": True,
            "message": f"Added {points} points to user {user_id}",
            "new_total": user_data[str(user_id)]["cloud_points"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/set-points/<int:user_id>/<int:points>', methods=['POST'])
def set_points_admin(user_id, points):
    """Set points for user (for testing)"""
    try:
        user_info = get_mock_user_data(user_id)
        user_data[str(user_id)]["cloud_points"] = points

        return jsonify({
            "success": True,
            "message": f"Set {points} points for user {user_id}",
            "new_total": user_data[str(user_id)]["cloud_points"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)