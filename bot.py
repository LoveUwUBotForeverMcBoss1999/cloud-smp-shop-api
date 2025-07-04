import os
import json
import asyncio
import discord
from discord.ext import commands

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
cloud_points = {}  # {user_id: points}
POINTS_CHANNEL_ID = 1390794341764567040
CLOUD_POINTS_FILE = 'cloud_points.txt'


# Helper functions
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


async def download_cloud_points():
    """Download and parse cloud points file from Discord"""
    try:
        channel = bot.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            return {}

        # Find the cloud points file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        content = await attachment.read()
                        return parse_cloud_points(content.decode('utf-8'))
        return {}
    except Exception as e:
        print(f"Error downloading cloud points: {e}")
        return {}


async def upload_cloud_points():
    """Upload cloud points file to Discord"""
    try:
        channel = bot.get_channel(POINTS_CHANNEL_ID)
        if not channel:
            return False

        # Delete existing file
        async for message in channel.history(limit=100):
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.filename == CLOUD_POINTS_FILE:
                        await message.delete()
                        break

        # Upload new file
        content = format_cloud_points(cloud_points)
        with open(CLOUD_POINTS_FILE, 'w') as f:
            f.write(content)

        with open(CLOUD_POINTS_FILE, 'rb') as f:
            file = discord.File(f, filename=CLOUD_POINTS_FILE)
            await channel.send(file=file)

        os.remove(CLOUD_POINTS_FILE)
        return True
    except Exception as e:
        print(f"Error uploading cloud points: {e}")
        return False


# Discord Bot Events
@bot.event
async def on_ready():
    print(f'🤖 {bot.user} has connected to Discord!')
    print(f'📊 Bot is serving {len(bot.guilds)} servers')

    # Load cloud points on startup
    global cloud_points
    cloud_points = await download_cloud_points()
    print(f"☁️ Loaded {len(cloud_points)} user cloud points")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Add 5 cloud points for each message
    user_id = str(message.author.id)
    if user_id not in cloud_points:
        cloud_points[user_id] = 0
    cloud_points[user_id] += 5

    # Upload updated points every 10 messages to avoid rate limits
    if sum(cloud_points.values()) % 50 == 0:  # Upload every 50 total points (10 messages)
        await upload_cloud_points()
        print(f"☁️ Updated cloud points for {len(cloud_points)} users")

    await bot.process_commands(message)


# Bot commands
@bot.command(name='points')
async def check_points(ctx):
    """Check user's cloud points"""
    user_id = str(ctx.author.id)
    points = cloud_points.get(user_id, 0)

    embed = discord.Embed(
        title="☁️ Cloud Points",
        description=f"You have **{points}** Cloud Points!",
        color=0x00ff00
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.add_field(name="💡 Tip", value="You earn 5 Cloud Points for each message you send!", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='leaderboard', aliases=['lb', 'top'])
async def leaderboard(ctx):
    """Show cloud points leaderboard"""
    if not cloud_points:
        await ctx.send("No cloud points data available yet!")
        return

    # Sort users by points
    sorted_users = sorted(cloud_points.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 Cloud Points Leaderboard",
        description="Top 10 users by Cloud Points",
        color=0xffd700
    )

    for i, (user_id, points) in enumerate(sorted_users, 1):
        try:
            user = bot.get_user(int(user_id))
            name = user.display_name if user else f"User {user_id}"
            embed.add_field(
                name=f"{i}. {name}",
                value=f"☁️ {points} points",
                inline=False
            )
        except:
            continue

    await ctx.send(embed=embed)


@bot.command(name='shop')
async def shop_info(ctx):
    """Show shop information"""
    embed = discord.Embed(
        title="🛒 Cloud Points Shop",
        description="Use our web shop to purchase items with your Cloud Points!",
        color=0x00aaff
    )

    embed.add_field(
        name="🌐 Web Shop",
        value="Visit our website to browse items and make purchases",
        inline=False
    )

    embed.add_field(
        name="🔒 Security",
        value="All purchases are secured with OTP verification sent to your DMs",
        inline=False
    )

    embed.add_field(
        name="💰 Your Points",
        value=f"☁️ {cloud_points.get(str(ctx.author.id), 0)} Cloud Points",
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync_points(ctx):
    """Manually sync cloud points (Admin only)"""
    await upload_cloud_points()
    await ctx.send("☁️ Cloud points synchronized successfully!")


# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    else:
        print(f"Error in command {ctx.command}: {error}")
        await ctx.send("❌ An error occurred while processing your command.")


# Run the bot
if __name__ == '__main__':
    bot.run(DISCORD_TOKEN)