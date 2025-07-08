from flask import Flask, jsonify, request, redirect, send_file
import os
import json
import requests
import random
import string
from datetime import datetime, timedelta
import time
import logging
import tempfile
from urllib.parse import urlparse

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
PTERODACTYL_API_KEY = os.getenv('PTERODACTYL_API_KEY')
PTERODACTYL_SERVER_ID = "13ded370"  # FIXED: Updated to your actual server ID
PTERODACTYL_BASE_URL = "https://panel2.mcboss.top/api/client/servers"  # FIXED: Updated to your panel URL
CHANNEL_ID = 1390794341764567040
DISCORD_API_BASE = "https://discord.com/api/v10"

# OTP storage (in production, use Redis or database)
active_otps = {}

# In-memory points storage for API (will be replaced by reading from Discord)
points_cache = {}
cache_timestamp = 0
CACHE_DURATION = 60  # 1 minute instead of 5 minutes



# Media channel configuration
MEDIA_CHANNEL_ID = 1390701938999558318  # The channel ID you specified

# Media type mappings
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.svg'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}

# Cache for media files
media_cache = {}
media_cache_timestamp = 0
MEDIA_CACHE_DURATION = 300  # 5 minutes cache for media




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
        return {}
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

        # If Discord fetch fails, clear cache and return empty
        logger.warning("Failed to fetch from Discord, clearing cache")
        points_cache = {}
        cache_timestamp = current_time
        return {}

    except Exception as e:
        logger.error(f"Error getting user data: {e}")
        # Clear cache on error
        points_cache = {}
        cache_timestamp = current_time
        return {}

def generate_otp():
    """Generate 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


def send_pterodactyl_command(command):
    """Send command to Pterodactyl server - COMPLETELY REWRITTEN"""
    if not PTERODACTYL_API_KEY:
        logger.error("Pterodactyl API key not configured!")
        return False

    try:
        # Construct the URL properly
        url = f"{PTERODACTYL_BASE_URL}/{PTERODACTYL_SERVER_ID}/command"

        # Headers with proper authentication
        headers = {
            'Authorization': f'Bearer {PTERODACTYL_API_KEY}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'CloudSMP-Shop-Bot/1.0'
        }

        # Command payload
        payload = {
            'command': command
        }

        logger.info(f"Sending command to Pterodactyl")
        logger.info(f"URL: {url}")
        logger.info(f"Command: {command}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Payload: {payload}")

        # Send the request with extended timeout
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        logger.info(f"Pterodactyl response status: {response.status_code}")
        logger.info(f"Pterodactyl response text: {response.text}")
        logger.info(f"Pterodactyl response headers: {dict(response.headers)}")

        # Handle different response codes
        if response.status_code == 204:
            # Success - command executed
            logger.info(f"✅ Successfully executed command: {command}")
            return True
        elif response.status_code == 200:
            # Some APIs return 200 instead of 204
            logger.info(f"✅ Command executed successfully: {command}")
            return True
        elif response.status_code == 401:
            logger.error("❌ Unauthorized - check Pterodactyl API key")
            logger.error(f"API Key being used: {PTERODACTYL_API_KEY[:10]}...")
            return False
        elif response.status_code == 403:
            logger.error("❌ Forbidden - insufficient permissions")
            return False
        elif response.status_code == 404:
            logger.error("❌ Server not found - check server ID")
            logger.error(f"Server ID being used: {PTERODACTYL_SERVER_ID}")
            logger.error(f"Full URL: {url}")
            return False
        elif response.status_code == 422:
            logger.error("❌ Validation error - check command format")
            logger.error(f"Command: {command}")
            return False
        elif response.status_code == 502:
            logger.error("❌ Server might be offline (502)")
            return False
        elif response.status_code == 429:
            logger.warning("⚠️ Rate limited")
            return False
        else:
            logger.error(f"❌ Pterodactyl API error: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.error("❌ Pterodactyl request timed out")
        return False
    except requests.exceptions.ConnectionError as e:
        logger.error(f"❌ Connection error to Pterodactyl: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Pterodactyl error: {e}")
        return False


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


def send_purchase_log_to_discord(user_id, username, item_name, item_price, ingame_name):
    """Send purchase log to Discord channel for points deduction"""
    try:
        # Shop log channel ID
        LOG_CHANNEL_ID = 1391019862389686392

        headers = get_discord_headers()

        # Create embed for purchase log
        embed_data = {
            "title": "🛒 Shop Purchase Log",
            "description": f"**{username}** purchased **{item_name}**",
            "color": 0x00FF00,  # Green color for successful purchase
            "fields": [
                {"name": "User ID", "value": str(user_id), "inline": True},
                {"name": "Username", "value": username, "inline": True},
                {"name": "In-Game Name", "value": ingame_name, "inline": True},
                {"name": "Item", "value": item_name, "inline": True},
                {"name": "Price", "value": f"☁️ {item_price}", "inline": True},
                {"name": "Status", "value": "✅ Successful", "inline": True}
            ],
            "footer": {"text": "CloudSMP Shop System"},
            "timestamp": datetime.now().isoformat()
        }

        # Send message to log channel
        message_url = f"{DISCORD_API_BASE}/channels/{LOG_CHANNEL_ID}/messages"
        message_data = {
            'embeds': [embed_data],
            'content': f"SHOP_PURCHASE:{user_id}:{item_price}:{username}:{item_name}"  # Bot will read this content
        }

        response = requests.post(message_url, headers=headers, json=message_data, timeout=10)

        if response.status_code == 200:
            logger.info(f"✅ Purchase log sent to Discord for user {user_id}")
            return True
        else:
            logger.error(f"❌ Failed to send purchase log: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Error sending purchase log to Discord: {e}")
        return False

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

    # Get items count from items.json
    items = load_items()
    items_count = len(items) if items else 0

    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "discord_token_configured": bool(DISCORD_TOKEN),
        "pterodactyl_configured": bool(PTERODACTYL_API_KEY),
        "pterodactyl_server_id": PTERODACTYL_SERVER_ID,
        "pterodactyl_base_url": PTERODACTYL_BASE_URL,
        "active_otps": len(active_otps),
        "cached_users": len(points_cache),
        "cache_age_seconds": int(time.time() - cache_timestamp) if cache_timestamp > 0 else 0,
        "shop_items_loaded": items_count
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
    """Purchase item using OTP verification"""
    try:
        logger.info(f"🛒 Purchase request: user_id={user_id}, otp={otp}, item={item_number}, ingame={ingame_name}")

        # Validate inputs
        if not user_id.isdigit() or len(user_id) < 10:
            logger.error(f"❌ Invalid user ID format: {user_id}")
            return jsonify({"error": "Invalid user ID format"}), 400

        if not otp.isdigit() or len(otp) != 6:
            logger.error(f"❌ Invalid OTP format: {otp}")
            return jsonify({"error": "Invalid OTP format"}), 400

        if not ingame_name or len(ingame_name) > 16:
            logger.error(f"❌ Invalid in-game name: {ingame_name}")
            return jsonify({"error": "Invalid in-game name"}), 400

        # Clean up expired OTPs
        cleanup_expired_otps()

        # Verify OTP
        user_id_str = str(user_id)
        logger.info(f"🔐 Checking OTP for user {user_id_str}")

        if user_id_str not in active_otps:
            logger.error(f"❌ No OTP found for user {user_id_str}")
            return jsonify({"error": "No OTP found or OTP expired"}), 400

        otp_data = active_otps[user_id_str]

        if otp_data["used"]:
            logger.error(f"❌ OTP already used for user {user_id_str}")
            return jsonify({"error": "OTP already used"}), 400

        if datetime.now() > otp_data["expires_at"]:
            logger.error(f"❌ OTP expired for user {user_id_str}")
            del active_otps[user_id_str]
            return jsonify({"error": "OTP expired"}), 400

        if otp_data["otp"] != otp:
            logger.error(f"❌ Invalid OTP for user {user_id_str}")
            return jsonify({"error": "Invalid OTP"}), 400

        logger.info(f"✅ OTP verified for user {user_id_str}")

        # Load items from items.json
        items = load_items()
        if not items:
            logger.error("❌ No items available")
            return jsonify({"error": "Shop items not available"}), 503

        if item_number not in items:
            logger.error(f"❌ Item {item_number} not found")
            return jsonify({"error": "Item not found"}), 404

        item = items[item_number]
        logger.info(f"📦 Item found: {item}")

        # Check user points
        all_user_data = get_user_from_channel()
        user_data = all_user_data.get(user_id_str, {})

        if not user_data:
            logger.error(f"❌ User {user_id_str} not found in user data")
            return jsonify({"error": "User not found"}), 404

        user_points = user_data.get("points", 0)
        logger.info(f"💰 User {user_id_str} has {user_points} points")

        # Get item price
        try:
            item_price = int(item["item-price"])
        except (ValueError, KeyError):
            logger.error(f"❌ Invalid item price for item {item_number}")
            return jsonify({"error": "Invalid item price"}), 500

        if user_points < item_price:
            logger.error(f"❌ User {user_id_str} has insufficient points ({user_points} < {item_price})")
            return jsonify({"error": "Insufficient cloud points"}), 400

        # Execute item command
        command = item["item-cmd"].replace("{ingame-name}", ingame_name)
        logger.info(f"🎮 Executing command: {command}")

        # Send command to Pterodactyl
        command_success = send_pterodactyl_command(command)

        if not command_success:
            logger.error(f"❌ Failed to execute command on Pterodactyl")
            return jsonify({"error": "Failed to execute command on server"}), 500

        # Mark OTP as used only if command succeeded
        active_otps[user_id_str]["used"] = True
        logger.info(f"✅ OTP marked as used for user {user_id_str}")

        # Send purchase log to Discord channel for points deduction
        try:
            purchase_log_sent = send_purchase_log_to_discord(user_id, user_data.get("username", "Unknown"), item["item-name"], item_price, ingame_name)
            logger.info(f"📝 Purchase log sent to Discord: {purchase_log_sent}")
        except Exception as e:
            logger.error(f"⚠️ Failed to send purchase log to Discord: {e}")
            # Continue with success response even if log fails

        logger.info(
            f"🎉 Purchase completed successfully: User {user_id} ({ingame_name}) bought {item['item-name']} for {item_price} points")

        return jsonify({
            "success": True,
            "message": "Purchase completed successfully",
            "item": item["item-name"],
            "price": item_price,
            "remaining_points": user_points - item_price,
            "command_executed": command,
            "pterodactyl_success": True
        })

    except Exception as e:
        logger.error(f"❌ Error purchasing item for {user_id}: {e}")
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


@app.route('/api/debug/pterodactyl-test')
def test_pterodactyl():
    """Test Pterodactyl connection"""
    try:
        command = "say Test command from API"
        success = send_pterodactyl_command(command)

        return jsonify({
            "pterodactyl_configured": bool(PTERODACTYL_API_KEY),
            "server_id": PTERODACTYL_SERVER_ID,
            "base_url": PTERODACTYL_BASE_URL,
            "test_command": command,
            "success": success
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500


@app.route('/api/admin/clear-cache', methods=['POST'])
def clear_cache():
    """Clear user data cache"""
    global points_cache, cache_timestamp
    points_cache = {}
    cache_timestamp = 0
    return jsonify({"message": "Cache cleared successfully"})


def get_file_extension(filename):
    """Get file extension from filename"""
    return os.path.splitext(filename.lower())[1]


def is_image_file(filename):
    """Check if file is an image"""
    extension = get_file_extension(filename)
    return extension in IMAGE_EXTENSIONS


def is_video_file(filename):
    """Check if file is a video"""
    extension = get_file_extension(filename)
    return extension in VIDEO_EXTENSIONS


def get_media_from_discord_channel():
    """Fetch media files from Discord channel with caching"""
    global media_cache, media_cache_timestamp

    current_time = time.time()

    # Use cache if it's fresh
    if current_time - media_cache_timestamp < MEDIA_CACHE_DURATION and media_cache:
        return media_cache

    max_retries = 3
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            headers = get_discord_headers()
            url = f"{DISCORD_API_BASE}/channels/{MEDIA_CHANNEL_ID}/messages"

            all_messages = []
            before = None

            # Fetch multiple pages of messages to get more media
            for page in range(5):  # Fetch up to 5 pages (500 messages)
                params = {'limit': 100}
                if before:
                    params['before'] = before

                response = requests.get(url, headers=headers, params=params, timeout=10)

                if response.status_code == 429:  # Rate limited
                    retry_after = int(response.headers.get('Retry-After', retry_delay))
                    logger.warning(f"Rate limited while fetching media, waiting {retry_after} seconds")
                    time.sleep(retry_after)
                    continue

                if response.status_code == 401:
                    logger.error("Discord API unauthorized - check bot token")
                    return {"images": [], "videos": []}

                if response.status_code != 200:
                    logger.error(f"Discord API error: {response.status_code} - {response.text}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (2 ** attempt))
                        continue
                    return {"images": [], "videos": []}

                messages = response.json()
                if not messages:
                    break

                all_messages.extend(messages)
                before = messages[-1]['id']

            # Process messages to extract media files
            images = []
            videos = []

            for message in all_messages:
                if message.get('attachments'):
                    for attachment in message['attachments']:
                        filename = attachment['filename']
                        url = attachment['url']
                        size = attachment.get('size', 0)

                        media_info = {
                            'filename': filename,
                            'url': url,
                            'size': size,
                            'message_id': message['id'],
                            'timestamp': message['timestamp'],
                            'author': message['author'].get('username', 'Unknown')
                        }

                        if is_image_file(filename):
                            images.append(media_info)
                        elif is_video_file(filename):
                            videos.append(media_info)

            # Sort by timestamp (latest first)
            images.sort(key=lambda x: x['timestamp'], reverse=True)
            videos.sort(key=lambda x: x['timestamp'], reverse=True)

            media_data = {
                "images": images,
                "videos": videos
            }

            # Update cache
            media_cache = media_data
            media_cache_timestamp = current_time

            logger.info(f"Updated media cache: {len(images)} images, {len(videos)} videos")
            return media_data

        except requests.RequestException as e:
            logger.error(f"Request error while fetching media (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))
                continue
            return {"images": [], "videos": []}
        except Exception as e:
            logger.error(f"Unexpected error fetching media: {e}")
            return {"images": [], "videos": []}

    return {"images": [], "videos": []}


def download_media_file(url, filename):
    """Download media file from Discord CDN"""
    try:
        headers = {
            'User-Agent': 'CloudSMP-Shop-Bot/1.0'
        }

        response = requests.get(url, headers=headers, timeout=30, stream=True)

        if response.status_code == 200:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=get_file_extension(filename))

            # Download in chunks
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    temp_file.write(chunk)

            temp_file.close()
            return temp_file.name
        else:
            logger.error(f"Failed to download media: {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Error downloading media file: {e}")
        return None


@app.route('/api/media/<media_type>/<int:number>')
def get_media(media_type, number):
    """Get media file by type and number (1-indexed)"""
    try:
        # Validate media type
        if media_type not in ['image', 'video']:
            return jsonify({"error": "Invalid media type. Use 'image' or 'video'"}), 400

        # Validate number
        if number < 1:
            return jsonify({"error": "Number must be 1 or greater"}), 400

        # Get media data from Discord
        media_data = get_media_from_discord_channel()

        if media_type == 'image':
            media_list = media_data['images']
        else:  # video
            media_list = media_data['videos']

        # Check if requested number exists
        if number > len(media_list):
            return jsonify({
                "error": f"Media not found. Only {len(media_list)} {media_type}s available"
            }), 404

        # Get the media file (convert to 0-indexed)
        media_file = media_list[number - 1]

        # Option 1: Redirect to Discord CDN URL (faster, but depends on Discord)
        if request.args.get('direct') == 'true':
            return redirect(media_file['url'])

        # Option 2: Proxy the file through our API (slower, but more reliable)
        try:
            # Download the file
            temp_file_path = download_media_file(media_file['url'], media_file['filename'])

            if temp_file_path:
                # Determine content type based on extension
                extension = get_file_extension(media_file['filename'])
                content_type_map = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif',
                    '.webp': 'image/webp',
                    '.bmp': 'image/bmp',
                    '.tiff': 'image/tiff',
                    '.svg': 'image/svg+xml',
                    '.mp4': 'video/mp4',
                    '.mov': 'video/quicktime',
                    '.avi': 'video/x-msvideo',
                    '.mkv': 'video/x-matroska',
                    '.webm': 'video/webm',
                    '.flv': 'video/x-flv',
                    '.wmv': 'video/x-ms-wmv',
                    '.m4v': 'video/x-m4v'
                }

                content_type = content_type_map.get(extension, 'application/octet-stream')

                def remove_temp_file():
                    try:
                        os.unlink(temp_file_path)
                    except:
                        pass

                # Send file and clean up after
                response = send_file(
                    temp_file_path,
                    mimetype=content_type,
                    as_attachment=False,
                    download_name=media_file['filename']
                )

                # Clean up temp file after sending
                response.call_on_close(remove_temp_file)

                return response
            else:
                # Fallback to redirect if download fails
                return redirect(media_file['url'])

        except Exception as e:
            logger.error(f"Error serving media file: {e}")
            # Fallback to redirect
            return redirect(media_file['url'])

    except Exception as e:
        logger.error(f"Error in get_media endpoint: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/media/<media_type>/info/<int:number>')
def get_media_info(media_type, number):
    """Get media file information without downloading"""
    try:
        # Validate media type
        if media_type not in ['image', 'video']:
            return jsonify({"error": "Invalid media type. Use 'image' or 'video'"}), 400

        # Validate number
        if number < 1:
            return jsonify({"error": "Number must be 1 or greater"}), 400

        # Get media data from Discord
        media_data = get_media_from_discord_channel()

        if media_type == 'image':
            media_list = media_data['images']
        else:  # video
            media_list = media_data['videos']

        # Check if requested number exists
        if number > len(media_list):
            return jsonify({
                "error": f"Media not found. Only {len(media_list)} {media_type}s available"
            }), 404

        # Get the media file info
        media_file = media_list[number - 1]

        return jsonify({
            "number": number,
            "type": media_type,
            "filename": media_file['filename'],
            "size": media_file['size'],
            "timestamp": media_file['timestamp'],
            "author": media_file['author'],
            "message_id": media_file['message_id'],
            "direct_url": media_file['url'],
            "api_url": f"/api/media/{media_type}/{number}"
        })

    except Exception as e:
        logger.error(f"Error in get_media_info endpoint: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/media/<media_type>/list')
def list_media(media_type):
    """List all available media files of a type"""
    try:
        # Validate media type
        if media_type not in ['image', 'video']:
            return jsonify({"error": "Invalid media type. Use 'image' or 'video'"}), 400

        # Get media data from Discord
        media_data = get_media_from_discord_channel()

        if media_type == 'image':
            media_list = media_data['images']
        else:  # video
            media_list = media_data['videos']

        # Format response
        formatted_list = []
        for i, media_file in enumerate(media_list, 1):
            formatted_list.append({
                "number": i,
                "filename": media_file['filename'],
                "size": media_file['size'],
                "timestamp": media_file['timestamp'],
                "author": media_file['author'],
                "api_url": f"/api/media/{media_type}/{i}",
                "info_url": f"/api/media/{media_type}/info/{i}"
            })

        return jsonify({
            "type": media_type,
            "total": len(media_list),
            "files": formatted_list
        })

    except Exception as e:
        logger.error(f"Error in list_media endpoint: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/media/stats')
def get_media_stats():
    """Get media statistics"""
    try:
        media_data = get_media_from_discord_channel()

        return jsonify({
            "total_images": len(media_data['images']),
            "total_videos": len(media_data['videos']),
            "total_media": len(media_data['images']) + len(media_data['videos']),
            "cache_age_seconds": int(time.time() - media_cache_timestamp) if media_cache_timestamp > 0 else 0,
            "supported_image_formats": list(IMAGE_EXTENSIONS),
            "supported_video_formats": list(VIDEO_EXTENSIONS)
        })

    except Exception as e:
        logger.error(f"Error in get_media_stats endpoint: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500


@app.route('/api/admin/clear-media-cache', methods=['POST'])
def clear_media_cache():
    """Clear media cache"""
    global media_cache, media_cache_timestamp
    media_cache = {}
    media_cache_timestamp = 0
    return jsonify({"message": "Media cache cleared successfully"})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
