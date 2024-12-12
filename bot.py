import os
import certifi
from dotenv import load_dotenv
import discord
from discord.ext import commands
import pymongo
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Chargement des variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)

# Récupération des informations de connexion MongoDB
MONGODB_URI = os.getenv('MONGODB_URI')
if not MONGODB_URI:
    raise ValueError("La variable d'environnement MONGODB_URI n'est pas définie")

# Nettoyage de l'URI si nécessaire
MONGODB_URI = MONGODB_URI.replace('directConnection=true', '')

print("URI MongoDB:", MONGODB_URI)

# Configuration MongoDB
try:
    client = pymongo.MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=5000,
        tls=True,
        tlsCAFile=certifi.where()  # Ajout du certificat SSL
    )
    # Test de connexion avec timeout
    client.admin.command('ping')
    print("Connexion à MongoDB réussie!")
except Exception as e:
    print(f"Erreur de connexion MongoDB: {e}")
    logging.error(f"Erreur MongoDB: {str(e)}", exc_info=True)
    client = None

# Initialisation des collections MongoDB
if client:
    db = client["HugoBot"]
    voice_times = db["voice_times"]
    voice_sessions = db["voice_sessions"]
else:
    print("Mode dégradé : fonctionnalités MongoDB désactivées")
    voice_times = None
    voice_sessions = None

# Vérification de la disponibilité de MongoDB
def check_mongodb():
    if not client or not voice_times or not voice_sessions:
        raise commands.CommandError("La base de données n'est pas disponible pour le moment.")

# Création du bot Discord
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Gestion des événements et commandes
@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.now()
    if before.channel is None and after.channel is not None:
        # L'utilisateur rejoint un salon vocal
        voice_states[member.id] = {
            'start_time': now,
            'channel_id': after.channel.id,
            'channel_name': after.channel.name
        }
    elif before.channel is not None and after.channel is None:
        # L'utilisateur quitte un salon vocal
        if member.id in voice_states:
            start_data = voice_states.pop(member.id)
            duration = (now - start_data['start_time']).total_seconds()
            if client:
                voice_sessions.insert_one({
                    'user_id': member.id,
                    'username': member.name,
                    'channel_id': start_data['channel_id'],
                    'channel_name': start_data['channel_name'],
                    'start_time': start_data['start_time'],
                    'end_time': now,
                    'duration': duration
                })
                voice_times.update_one(
                    {"user_id": member.id},
                    {"$inc": {"total_time": duration}, "$set": {"username": member.name}},
                    upsert=True
                )

@bot.event
async def on_ready():
    print(f'Bot connecté en tant que {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('-------------------')

@bot.command()
async def stats_jour(ctx):
    check_mongodb()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = voice_sessions.find({'user_id': ctx.author.id, 'start_time': {'$gte': today}})
    total_time = sum(session['duration'] for session in sessions)
    await ctx.send(f"Aujourd'hui, vous avez passé {round(total_time / 60)} minutes en vocal!")

@bot.command()
async def top(ctx, limit: int = 5):
    check_mongodb()
    top_users = voice_times.find().sort("total_time", -1).limit(limit)
    embed = discord.Embed(title=f"Top {limit} - Temps en vocal", color=discord.Color.blue())
    for i, user in enumerate(top_users, 1):
        minutes = round(user["total_time"] / 60)
        embed.add_field(name=f"#{i} {user['username']}", value=f"{minutes} minutes", inline=False)
    await ctx.send(embed=embed)

if __name__ == "__main__":
    print("Démarrage du bot...")
    bot.run(os.getenv('DISCORD_TOKEN'))
