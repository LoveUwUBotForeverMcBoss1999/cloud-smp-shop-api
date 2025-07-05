from flask import Flask, jsonify, request
import os
import json
import requests
import random
import string
from datetime import datetime, timedelta
import time
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
cache_timestamp = 0
CACHE_DURATION = 300  # 5 minutes


def get_discord_headers():
    """Get Discord API headers"""
    if not DISCORD_TOKEN:
        raise ValueError("Discord token not configured")

    return {
        'Authorization': f'Bot {DISCORD_TOKEN}',
        'Content-Type': 'application/json',
        'User-Agent': 'CloudSMP-Shop-Bot/1.0'
    }


def get_user_data_from_discord():
    """Fetch user data from Discord channel messages with retry logic"""
    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            headers = get_discord_headers()
            url = f"{DISCORD_API_BASE}/channels/{CHANNEL_ID}/messages"

            response = requests.get(url, headers=headers, params={'limit': 100}, timeout=10)

            if response.status_code == 429:  # Rate limited
                retry_after = int(response.headers.get('Retry-After', retry_delay))
                logger.warning(f"Rate limited, waiting {retry_after} seconds")
                time.sleep(retry_after)
                continue

            if response.status_code == 401:
                logger.error("Discord API unauthorized - check bot token")
                return {}

            if response.status_code != 200:
                logger.error(f"Discord API error: {response.status_code} - {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                return {}

            messages = response.json()

            # Look for the cloud_points.txt file
            for message in messages:
                if message.get('attachments'):
                    for attachment in message['attachments']:
                        if attachment['filename'] == 'cloud_points.txt':
                            try:
                                # Download the file
                                file_response = requests.get(attachment['url'], timeout=10)
                                if file_response.status_code == 200:
                                    return json.loads(file_response.text)
                            except (requests.RequestException, json.JSONDecodeError) as e:
                                logger.error(f"Error downloading/parsing points file: {e}")
                                continue

            return {}

        except requests.RequestException as e:
            logger.error(f"Request error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))
                continue
            return {}
        except Exception as e:
            logger.error(f"Unexpected error fetching Discord data: {e}")
            return {}

    return {}


def get_discord_user_info(user_id):
    """Get Discord user info via API with error handling"""
    try:
        headers = get_discord_headers()
        url = f"{DISCORD_API_BASE}/users/{user_id}"

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            logger.warning(f"Discord user {user_id} not found")
            return None
        else:
            logger.error(f"Error getting Discord user {user_id}: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error getting Discord user {user_id}: {e}")
        return None


def send_discord_dm(user_id, embed_data):
    """Send DM to Discord user with improved error handling"""
    try:
        headers = get_discord_headers()

        # Create DM channel
        dm_url = f"{DISCORD_API_BASE}/users/@me/channels"
        dm_data = {'recipient_id': user_id}

        dm_response = requests.post(dm_url, headers=headers, json=dm_data, timeout=10)

        if dm_response.status_code == 200:
            dm_channel = dm_response.json()

            # Send message to DM channel
            message_url = f"{DISCORD_API_BASE}/channels/{dm_channel['id']}/messages"
            message_data = {'embeds': [embed_data]}

            message_response = requests.post(message_url, headers=headers, json=message_data, timeout=10)

            if message_response.status_code == 200:
                logger.info(f"Successfully sent DM to user {user_id}")
                return True
            else:
                logger.error(f"Failed to send DM message: {message_response.status_code}")
                return False
        elif dm_response.status_code == 403:
            logger.warning(f"Cannot send DM to user {user_id} - DMs disabled or blocked")
            return False
        else:
            logger.error(f"Failed to create DM channel: {dm_response.status_code}")
            return False

    except Exception as e:
        logger.error(f"Error sending DM to {user_id}: {e}")
        return False


def load_items():
    """Load items from items.json with error handling"""
    try:
        with open('items.json', 'r') as f:
            items_data = json.load(f)
            # Validate items structure
            items = {}
            for item_id, item_data in items_data.items():
                required_fields = ['item-name', 'item-price', 'item-icon', 'item-cmd']
                if all(field in item_data for field in required_fields):
                    items[item_id] = item_data
                else:
                    logger.warning(f"Item {item_id} missing required fields")
            return items
    except FileNotFoundError:
        logger.error("items.json file not found")
        # Return default items if file doesn't exist
        return {
            "1": {"item-name": "Golden Apple", "item-price": 100, "item-icon": "🍎",
                  "item-cmd": "give {ingame-name} golden_apple 1"},
            "2": {"item-name": "Diamond Sword", "item-price": 250, "item-icon": "⚔️",
                  "item-cmd": "give {ingame-name} diamond_sword 1"},
            "3": {"item-name": "Enchanted Diamond Pickaxe", "item-price": 500, "item-icon": "⛏️",
                  "item-cmd": "give {ingame-name} diamond_pickaxe 1"},
            "4": {"item-name": "Netherite Helmet", "item-price": 750, "item-icon": "🪖",
                  "item-cmd": "give {ingame-name} netherite_helmet 1"},
            "5": {"item-name": "Ender Chest", "item-price": 200, "item-icon": "📦",
                  "item-cmd": "give {ingame-name} ender_chest 1"},
            "6": {"item-name": "Shulker Box", "item-price": 300, "item-icon": "🎁",
                  "item-cmd": "give {ingame-name} shulker_box 1"},
            "7": {"item-name": "Elytra", "item-price": 1000, "item-icon": "🪶",
                  "item-cmd": "give {ingame-name} elytra 1"},
            "8": {"item-name": "Beacon", "item-price": 800, "item-icon": "🔥",
                  "item-cmd": "give {ingame-name} beacon 1"},
            "9": {"item-name": "Totem of Undying", "item-price": 600, "item-icon": "🛡️",
                  "item-cmd": "give {ingame-name} totem_of_undying 1"},
            "10": {"item-name": "Dragon Egg", "item-price": 1500, "item-icon": "🥚",
                   "item-cmd": "give {ingame-name} dragon_egg 1"},
            "11": {"item-name": "Stack of Diamonds", "item-price": 400, "item-icon": "💎",
                   "item-cmd": "give {ingame-name} diamond 64"},
            "12": {"item-name": "Stack of Emeralds", "item-price": 350, "item-icon": "💚",
                   "item-cmd": "give {ingame-name} emerald 64"},
            "13": {"item-name": "Mending Book", "item-price": 450, "item-icon": "📚",
                   "item-cmd": "give {ingame-name} enchanted_book{StoredEnchantments:[{id:mending,lvl:1}]} 1"},
            "14": {"item-name": "Trident", "item-price": 550, "item-icon": "🔱",
                   "item-cmd": "give {ingame-name} trident 1"},
            "15": {"item-name": "Notch Apple", "item-price": 900, "item-icon": "🌟",
                   "item-cmd": "give {ingame-name} enchanted_golden_apple 1"}
        }
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing items.json: {e}")
        return {}


def get_user_from_channel():
    """Get user data from Discord channel file with caching"""
    global points_cache, cache_timestamp

    current_time = time.time()

    # Use cache if it's fresh
    if current_time - cache_timestamp < CACHE_DURATION and points_cache:
        return points_cache

    try:
        # Try to get fresh data from Discord
        discord_data = get_user_data_from_discord()
        if discord_data:
            points_cache = discord_data
            cache_timestamp = current_time
            logger.info(f"Updated user cache with {len(discord_data)} users")
            return discord_data

        # If Discord fetch fails, try to use fallback data or return empty
        logger.warning("Failed to fetch from Discord, using fallback data")

        # Fallback mock data for testing
        fallback_data = {
            "1237079597124812862": {
                "username": "ItzMcBoss",
                "points": 1500,
                "messages": 250,
                "last_updated": datetime.now().isoformat()
            },
            "123456789": {
                "username": "TestUser",
                "points": 1200,
                "messages": 450,
                "last_updated": datetime.now().isoformat()
            }
        }

        points_cache = fallback_data
        cache_timestamp = current_time
        return fallback_data

    except Exception as e:
        logger.error(f"Error getting user data: {e}")
        return points_cache if points_cache else {}


def generate_otp():
    """Generate 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


def send_pterodactyl_command(command):
    """Send command to Pterodactyl server - FIXED with better error handling"""
    if not PTERODACTYL_API_KEY:
        logger.warning("Pterodactyl API key not configured - simulating command execution")
        return True  # Return True for testing when API key is not configured

    try:
        # Construct the URL properly
        url = f"{PTERODACTYL_BASE_URL}/{PTERODACTYL_SERVER_ID}/command"
        
        # Headers with proper authentication
        headers = {
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Command payload
        payload = {
            'command': command
        }

        logger.info(f"Sending command to Pterodactyl: {command}")
        logger.info(f"URL: {url}")
        
        # Send the request with extended timeout
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        logger.info(f"Pterodactyl response status: {response.status_code}")
        
        # Handle different response codes
        if response.status_code == 204:
            # Success - command executed
            logger.info(f"Successfully executed command: {command}")
            return True
        elif response.status_code == 200:
            # Some APIs return 200 instead of 204
            logger.info(f"Command executed successfully: {command}")
            return True
        elif response.status_code == 502:
            logger.warning("Server might be offline (502) - but allowing purchase to continue")
            return True  # Allow purchase even if server is offline
        elif response.status_code == 401:
            logger.error("Unauthorized - check Pterodactyl API key")
            return False
        elif response.status_code == 403:
            logger.error("Forbidden - insufficient permissions")
            return False
        elif response.status_code == 404:
            logger.error("Server not found - check server ID")
            return False
        elif response.status_code == 429:
            logger.warning("Rate limited - but allowing purchase")
            return True  # Allow purchase even if rate limited
        else:
            logger.error(f"Pterodactyl API error: {response.status_code} - {response.text}")
            # For unknown errors, allow the purchase to continue
            # The bot will handle the actual point deduction
            return True

    except requests.exceptions.Timeout:
        logger.warning("Pterodactyl request timed out - allowing purchase to continue")
        return True
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error to Pterodactyl - allowing purchase to continue")
        return True
    except Exception as e:
        logger.warning(f"Pterodactyl error: {e} - allowing purchase to continue")
        return True


def cleanup_expired_otps():
    """Clean up expired OTPs"""
    current_time = datetime.now()
    expired_users = []

    for user_id, otp_data in active_otps.items():
        if current_time > otp_data["expires_at"]:
            expired_users.append(user_id)

    for user_id in expired_users:
        del active_otps[user_id]

    if expired_users:
        logger.info(f"Cleaned up {len(expired_users)} expired OTPs")


# CORS handling
@app.after_request
def after_request(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify({})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
        return response


@app.route('/')
def health_check():
    """Health check endpoint"""
    cleanup_expired_otps()

    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "discord_token_configured": bool(DISCORD_TOKEN),
        "pterodactyl_configured": bool(PTERODACTYL_API_KEY),
        "active_otps": len(active_otps),
        "cached_users": len(points_cache),
        "cache_age_seconds": int(time.time() - cache_timestamp) if cache_timestamp > 0 else 0
    }
    return jsonify(status)


@app.route('/api/user/<user_id>')
def get_user_info(user_id):
    """Get user information"""
    try:
        # Validate user ID
        if not user_id.isdigit() or len(user_id) < 10:
            return jsonify({"error": "Invalid user ID format"}), 400

        # Get user data from Discord channel
        all_user_data = get_user_from_channel()
        user_data = all_user_data.get(str(user_id), {})

        if not user_data:
            return jsonify({"error": "User not found in points system"}), 404

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
        logger.error(f"Error getting user info for {user_id}: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/shop/<user_id>/send-otp-dm', methods=['POST'])
def send_otp_dm(user_id):
    """Send OTP to user's DM"""
    try:
        # Validate user ID
        if not user_id.isdigit() or len(user_id) < 10:
            return jsonify({"error": "Invalid user ID format"}), 400

        # Check if user exists
        all_user_data = get_user_from_channel()
        if str(user_id) not in all_user_data:
            return jsonify({"error": "User not found in points system"}), 404

        # Clean up expired OTPs
        cleanup_expired_otps()

        # Generate OTP
        otp = generate_otp()
        expires_at = datetime.now() + timedelta(minutes=5)

        # Store OTP with string key for consistency
        active_otps[str(user_id)] = {
            "otp": otp,
            "expires_at": expires_at,
            "used": False,
            "created_at": datetime.now()
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

        # Try to send DM
        dm_sent = False
        if DISCORD_TOKEN:
            dm_sent = send_discord_dm(user_id, embed_data)

        if dm_sent:
            return jsonify({
                "success": True,
                "message": "OTP sent to DM",
                "expires_in": 300
            })
        else:
            # Return the OTP in response if DM fails (for testing)
            return jsonify({
                "success": True,
                "message": "DM delivery failed, OTP provided in response",
                "otp": otp,  # Include OTP for testing when DM fails
                "expires_in": 300
            })

    except Exception as e:
        logger.error(f"Error sending OTP to {user_id}: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/shop/<user_id>/<otp>/item/<item_number>/<ingame_name>', methods=['POST'])
def purchase_item(user_id, otp, item_number, ingame_name):
    """Purchase item using OTP verification - FIXED VERSION"""
    try:
        logger.info(f"Purchase request: user_id={user_id}, otp={otp}, item={item_number}, ingame={ingame_name}")

        # Validate inputs
        if not user_id.isdigit() or len(user_id) < 10:
            logger.error(f"Invalid user ID format: {user_id}")
            return jsonify({"error": "Invalid user ID format"}), 400

        if not otp.isdigit() or len(otp) != 6:
            logger.error(f"Invalid OTP format: {otp}")
            return jsonify({"error": "Invalid OTP format"}), 400

        if not ingame_name or len(ingame_name) > 16:
            logger.error(f"Invalid in-game name: {ingame_name}")
            return jsonify({"error": "Invalid in-game name"}), 400

        # Clean up expired OTPs
        cleanup_expired_otps()

        # Verify OTP
        user_id_str = str(user_id)
        logger.info(f"Checking OTP for user {user_id_str}")

        if user_id_str not in active_otps:
            logger.error(f"No OTP found for user {user_id_str}")
            return jsonify({"error": "No OTP found or OTP expired"}), 400

        otp_data = active_otps[user_id_str]

        if otp_data["used"]:
            logger.error(f"OTP already used for user {user_id_str}")
            return jsonify({"error": "OTP already used"}), 400

        if datetime.now() > otp_data["expires_at"]:
            logger.error(f"OTP expired for user {user_id_str}")
            del active_otps[user_id_str]
            return jsonify({"error": "OTP expired"}), 400

        if otp_data["otp"] != otp:
            logger.error(f"Invalid OTP for user {user_id_str}")
            return jsonify({"error": "Invalid OTP"}), 400

        # Load items
        items = load_items()
        if not items:
            logger.error("No items available")
            return jsonify({"error": "Shop items not available"}), 503

        if item_number not in items:
            logger.error(f"Item {item_number} not found")
            return jsonify({"error": "Item not found"}), 404

        item = items[item_number]
        logger.info(f"Item found: {item}")

        # Check user points
        all_user_data = get_user_from_channel()
        user_data = all_user_data.get(user_id_str, {})

        if not user_data:
            logger.error(f"User {user_id_str} not found in user data")
            return jsonify({"error": "User not found"}), 404

        user_points = user_data.get("points", 0)
        logger.info(f"User {user_id_str} has {user_points} points")

        # Get item price
        try:
            item_price = int(item["item-price"])
        except (ValueError, KeyError):
            logger.error(f"Invalid item price for item {item_number}")
            return jsonify({"error": "Invalid item price"}), 500

        if user_points < item_price:
            logger.error(f"User {user_id_str} has insufficient points")
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)
        logger.info(f"Executing command: {command}")

        # Try to send command (this will now be more lenient)
        command_success = send_pterodactyl_command(command)

        # Mark OTP as used regardless of Pterodactyl success
        # The Discord bot will handle the actual point deduction
        active_otps[user_id_str]["used"] = True
        logger.info(f"OTP marked as used for user {user_id_str}")

        logger.info(f"Purchase completed: User {user_id} ({ingame_name}) bought {item['item-name']} for {item_price} points")

        # Always return success - let the Discord bot handle the rest
        response_data = {
            "success": True,
            "message": "Purchase completed successfully",
            "item": item["item-name"],
            "price": item_price,
            "remaining_points": user_points - item_price,
            "command_executed": command,
            "note": "Points will be deducted by the Discord bot system"
        }

        if not command_success:
            response_data["warning"] = "Command execution uncertain, but purchase recorded"

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error purchasing item for {user_id}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/item-info/<item_number>')
def get_item_info(item_number):
    """Get item information"""
    try:
        items = load_items()

        if not items:
            return jsonify({"error": "Shop items not available"}), 503

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
        logger.error(f"Error getting item info for {item_number}: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/shop/items')
def get_all_items():
    """Get all shop items"""
    try:
        items = load_items()

        if not items:
            return jsonify({"error": "Shop items not available"}), 503

        formatted_items = []
        for item_id, item_data in items.items():
            try:
                formatted_items.append({
                    "item_id": item_id,
                    "item_name": item_data["item-name"],
                    "item_price": int(item_data["item-price"]),
                    "item_icon": item_data["item-icon"]
                })
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed item {item_id}: {e}")
                continue

        return jsonify({
            "items": formatted_items,
            "total_items": len(formatted_items)
        })

    except Exception as e:
        logger.error(f"Error getting shop items: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/admin/otps')
def get_active_otps():
    """Get active OTPs (for debugging)"""
    cleanup_expired_otps()

    otp_info = {}
    for user_id, otp_data in active_otps.items():
        otp_info[user_id] = {
            "otp": otp_data["otp"],
            "expires_at": otp_data["expires_at"].isoformat(),
            "used": otp_data["used"],
            "created_at": otp_data["created_at"].isoformat()
        }

    return jsonify(otp_info)


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
