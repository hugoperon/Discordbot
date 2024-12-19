import os
import discord
from discord.ext import commands
import pymongo
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration MongoDB
MONGODB_URI = os.getenv('MONGODB_URI')
try:
    client = pymongo.MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=30000,
        tls=True,
        tlsAllowInvalidCertificates=True,
        retryWrites=True,
        w='majority',
        connectTimeoutMS=30000,
        socketTimeoutMS=None,
        maxPoolSize=50
    )
    # Test de connexion
    client.admin.command('ping')
    print("Connexion à MongoDB réussie!")
    
    # Initialisation des collections
    db = client["HugoBot"]  # Assurez-vous que c'est le bon nom de base de données
    voice_times = db["voice_times"]
    voice_sessions = db["voice_sessions"]
except Exception as e:
    print(f"Erreur de connexion MongoDB: {e}")
    client = None
    voice_times = None
    voice_sessions = None

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Dictionnaire pour stocker les sessions actives
voice_states = {}

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
            start_data = voice_states[member.id]
            duration = (now - start_data['start_time']).total_seconds()
            
            # Enregistrer la session
            session = {
                'user_id': member.id,
                'username': member.name,
                'channel_id': start_data['channel_id'],
                'channel_name': start_data['channel_name'],
                'start_time': start_data['start_time'],
                'end_time': now,
                'duration': duration
            }
            voice_sessions.insert_one(session)
            
            # Mettre à jour les stats globales
            voice_times.update_one(
                {"user_id": member.id},
                {
                    "$inc": {"total_time": duration},
                    "$set": {"username": member.name}
                },
                upsert=True
            )
            
            del voice_states[member.id]

@bot.command()
async def stats_jour(ctx):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sessions = voice_sessions.find({
        'user_id': ctx.author.id,
        'start_time': {'$gte': today}
    })
    
    total_time = sum(session['duration'] for session in sessions)
    minutes = round(total_time / 60)
    
    await ctx.send(f"Aujourd'hui, vous avez passé {minutes} minutes en vocal!")

@bot.command()
async def stats_semaine(ctx):
    week_ago = datetime.now() - timedelta(days=7)
    sessions = voice_sessions.find({
        'user_id': ctx.author.id,
        'start_time': {'$gte': week_ago}
    })
    
    daily_times = defaultdict(int)
    for session in sessions:
        day = session['start_time'].strftime('%A')  # Jour de la semaine
        daily_times[day] += session['duration']
    
    embed = discord.Embed(title="Statistiques hebdomadaires", color=discord.Color.blue())
    for day, time in daily_times.items():
        embed.add_field(name=day, value=f"{round(time/60)} minutes", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def stats_mois(ctx):
    month_ago = datetime.now() - timedelta(days=30)
    total_time = voice_sessions.aggregate([
        {
            '$match': {
                'user_id': ctx.author.id,
                'start_time': {'$gte': month_ago}
            }
        },
        {
            '$group': {
                '_id': None,
                'total': {'$sum': '$duration'}
            }
        }
    ])
    
    result = next(total_time, {'total': 0})
    hours = round(result['total'] / 3600, 1)
    
    await ctx.send(f"Ce mois-ci, vous avez passé {hours} heures en vocal!")

@bot.command()
async def moyenne(ctx):
    sessions = voice_sessions.find({'user_id': ctx.author.id})
    total_time = 0
    days = defaultdict(float)
    
    for session in sessions:
        day = session['start_time'].date()
        days[day] += session['duration']
        total_time += session['duration']
    
    if len(days) > 0:
        avg_time = total_time / len(days)
        await ctx.send(f"En moyenne, vous passez {round(avg_time/60)} minutes par jour en vocal!")
    else:
        await ctx.send("Pas encore assez de données pour calculer une moyenne!")

@bot.command()
async def top_salon(ctx):
    sessions = voice_sessions.aggregate([
        {
            '$match': {'user_id': ctx.author.id}
        },
        {
            '$group': {
                '_id': '$channel_name',
                'total_time': {'$sum': '$duration'}
            }
        },
        {
            '$sort': {'total_time': -1}
        }
    ])
    
    embed = discord.Embed(title="Temps par salon", color=discord.Color.green())
    for salon in sessions:
        hours = round(salon['total_time'] / 3600, 1)
        embed.add_field(name=salon['_id'], value=f"{hours}h", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def compare(ctx, user: discord.Member):
    user1_time = voice_times.find_one({'user_id': ctx.author.id})
    user2_time = voice_times.find_one({'user_id': user.id})
    
    embed = discord.Embed(title="Comparaison", color=discord.Color.gold())
    embed.add_field(
        name=ctx.author.name,
        value=f"{round(user1_time.get('total_time', 0)/3600, 1)}h",
        inline=True
    )
    embed.add_field(
        name=user.name,
        value=f"{round(user2_time.get('total_time', 0)/3600, 1)}h",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command()
async def duo(ctx, user: discord.Member):
    # Trouver les sessions où les deux utilisateurs étaient dans le même salon
    user1_sessions = list(voice_sessions.find({'user_id': ctx.author.id}))
    user2_sessions = list(voice_sessions.find({'user_id': user.id}))
    
    total_duo_time = 0
    for session1 in user1_sessions:
        for session2 in user2_sessions:
            if (session1['channel_id'] == session2['channel_id'] and
                session1['start_time'] < session2['end_time'] and
                session2['start_time'] < session1['end_time']):
                # Calculer le temps de chevauchement
                overlap_start = max(session1['start_time'], session2['start_time'])
                overlap_end = min(session1['end_time'], session2['end_time'])
                total_duo_time += (overlap_end - overlap_start).total_seconds()
    
    hours = round(total_duo_time / 3600, 1)
    await ctx.send(f"Vous avez passé {hours}h en vocal ensemble!")

# Fonction utilitaire pour vérifier les streaks
def get_streak_days(user_id):
    sessions = voice_sessions.find({'user_id': user_id}).sort('start_time', 1)
    days = set()
    current_streak = 0
    best_streak = 0
    last_day = None
    
    for session in sessions:
        day = session['start_time'].date()
        days.add(day)
        
        if last_day is None:
            current_streak = 1
        elif (day - last_day).days == 1:
            current_streak += 1
        elif (day - last_day).days > 1:
            best_streak = max(best_streak, current_streak)
            current_streak = 1
            
        last_day = day
    
    best_streak = max(best_streak, current_streak)
    return current_streak, best_streak

@bot.command()
async def streak(ctx):
    current_streak, _ = get_streak_days(ctx.author.id)
    await ctx.send(f"Votre série actuelle est de {current_streak} jours!")

@bot.command()
async def best_streak(ctx):
    _, best_streak = get_streak_days(ctx.author.id)
    await ctx.send(f"Votre meilleure série est de {best_streak} jours!")

@bot.command()
async def temps(ctx):
    # Affiche le temps total d'un utilisateur
    user_data = voice_times.find_one({"user_id": ctx.author.id})
    if user_data:
        total_minutes = round(user_data["total_time"] / 60)
        await ctx.send(f"Vous avez passé {total_minutes} minutes en vocal!")
    else:
        await ctx.send("Vous n'avez pas encore passé de temps en vocal!")

@bot.command()
async def top(ctx, limit: int = 5):
    # Affiche le top X des utilisateurs
    top_users = voice_times.find().sort("total_time", -1).limit(limit)
    
    embed = discord.Embed(title=f"Top {limit} - Temps en vocal", color=discord.Color.blue())
    for i, user in enumerate(top_users, 1):
        minutes = round(user["total_time"] / 60)
        embed.add_field(
            name=f"#{i} {user['username']}", 
            value=f"{minutes} minutes",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def mes_salons(ctx):
    # Récupérer toutes les sessions de l'utilisateur groupées par salon
    salons_stats = voice_sessions.aggregate([
        {
            '$match': {'user_id': ctx.author.id}
        },
        {
            '$group': {
                '_id': {
                    'channel_id': '$channel_id',
                    'channel_name': '$channel_name'
                },
                'total_time': {'$sum': '$duration'},
                'sessions_count': {'$sum': 1}
            }
        },
        {
            '$sort': {'total_time': -1}
        }
    ])
    
    embed = discord.Embed(
        title=f"Temps passé par salon pour {ctx.author.name}",
        color=discord.Color.blue()
    )
    
    for salon in salons_stats:
        heures = round(salon['total_time'] / 3600, 1)
        sessions = salon['sessions_count']
        embed.add_field(
            name=salon['_id']['channel_name'],
            value=f"⏰ {heures}h\n🔄 {sessions} sessions",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def user_temps(ctx, user: discord.Member):
    # Récupérer les stats de l'utilisateur mentionné
    user_data = voice_times.find_one({"user_id": user.id})
    
    if user_data:
        total_minutes = round(user_data["total_time"] / 60)
        total_heures = round(total_minutes / 60, 1)
        
        embed = discord.Embed(
            title=f"Statistiques de {user.name}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Temps total",
            value=f"⏰ {total_heures} heures ({total_minutes} minutes)",
            inline=False
        )
        
        # Ajouter le temps aujourd'hui
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_sessions = voice_sessions.find({
            'user_id': user.id,
            'start_time': {'$gte': today}
        })
        today_time = sum(session['duration'] for session in today_sessions)
        today_minutes = round(today_time / 60)
        
        embed.add_field(
            name="Aujourd'hui",
            value=f"⌛ {today_minutes} minutes",
            inline=False
        )
        
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"{user.name} n'a pas encore passé de temps en vocal!")

if __name__ == "__main__":
    bot.run(os.getenv('DISCORD_TOKEN')) 