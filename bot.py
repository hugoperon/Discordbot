import os
import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration SQLite
def init_db():
    # Utiliser un chemin absolu pour la base de données
    db_path = os.path.join(os.getcwd(), 'voice_stats.db')
    print(f"Base de données SQLite: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Pour avoir accès aux colonnes par nom
    
    # Création des tables
    cursor = conn.cursor()
    
    # Table pour les temps totaux
    cursor.execute('''CREATE TABLE IF NOT EXISTS voice_times
                     (user_id INTEGER PRIMARY KEY,
                      username TEXT,
                      total_time REAL DEFAULT 0)''')
    
    # Table pour les sessions individuelles
    cursor.execute('''CREATE TABLE IF NOT EXISTS voice_sessions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      channel_id INTEGER,
                      channel_name TEXT,
                      start_time TIMESTAMP,
                      end_time TIMESTAMP,
                      duration REAL)''')
    
    conn.commit()
    print("Tables de la base de données créées avec succès")
    return conn

# Initialisation de la base de données
db = init_db()

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
            db.execute('''
                INSERT INTO voice_sessions 
                (user_id, username, channel_id, channel_name, start_time, end_time, duration) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (member.id, member.name, start_data['channel_id'], 
                 start_data['channel_name'], start_data['start_time'], now, duration))
            
            # Mettre à jour ou créer l'entrée dans voice_times
            db.execute('''
                INSERT INTO voice_times (user_id, username, total_time)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                total_time = total_time + ?,
                username = ?
            ''', (member.id, member.name, duration, duration, member.name))
            
            db.commit()
            del voice_states[member.id]

@bot.command()
async def stats_jour(ctx):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cursor = db.execute('SELECT total_time FROM voice_times WHERE user_id = ? AND start_time >= ?', (ctx.author.id, today))
    total_time = sum(row[0] for row in cursor)
    minutes = round(total_time / 60)
    
    await ctx.send(f"Aujourd'hui, vous avez passé {minutes} minutes en vocal!")

@bot.command()
async def stats_semaine(ctx):
    week_ago = datetime.now() - timedelta(days=7)
    cursor = db.execute('SELECT total_time FROM voice_sessions WHERE user_id = ? AND start_time >= ?', (ctx.author.id, week_ago))
    daily_times = defaultdict(int)
    for row in cursor:
        day = datetime.fromtimestamp(row[0]).strftime('%A')  # Jour de la semaine
        daily_times[day] += row[0]
    
    embed = discord.Embed(title="Statistiques hebdomadaires", color=discord.Color.blue())
    for day, time in daily_times.items():
        embed.add_field(name=day, value=f"{round(time/60)} minutes", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def stats_mois(ctx):
    month_ago = datetime.now() - timedelta(days=30)
    cursor = db.execute('SELECT SUM(duration) FROM voice_sessions WHERE user_id = ? AND start_time >= ?', (ctx.author.id, month_ago))
    total_time = next(cursor, {'SUM(duration)': 0})['SUM(duration)']
    hours = round(total_time / 3600, 1)
    
    await ctx.send(f"Ce mois-ci, vous avez passé {hours} heures en vocal!")

@bot.command()
async def moyenne(ctx):
    cursor = db.execute('SELECT duration FROM voice_sessions WHERE user_id = ?', (ctx.author.id,))
    total_time = 0
    days = defaultdict(float)
    
    for row in cursor:
        day = datetime.fromtimestamp(row[0]).date()
        days[day] += row[0]
        total_time += row[0]
    
    if len(days) > 0:
        avg_time = total_time / len(days)
        await ctx.send(f"En moyenne, vous passez {round(avg_time/60)} minutes par jour en vocal!")
    else:
        await ctx.send("Pas encore assez de données pour calculer une moyenne!")

@bot.command()
async def top_salon(ctx):
    cursor = db.execute('SELECT channel_name, SUM(duration) FROM voice_sessions WHERE user_id = ? GROUP BY channel_name ORDER BY SUM(duration) DESC', (ctx.author.id,))
    embed = discord.Embed(title="Temps par salon", color=discord.Color.green())
    for row in cursor:
        hours = round(row[1] / 3600, 1)
        embed.add_field(name=row[0], value=f"{hours}h", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def compare(ctx, user: discord.Member):
    cursor = db.execute('SELECT total_time FROM voice_times WHERE user_id = ?', (ctx.author.id,))
    user1_time = next(cursor, {'total_time': 0})['total_time']
    cursor = db.execute('SELECT total_time FROM voice_times WHERE user_id = ?', (user.id,))
    user2_time = next(cursor, {'total_time': 0})['total_time']
    
    embed = discord.Embed(title="Comparaison", color=discord.Color.gold())
    embed.add_field(
        name=ctx.author.name,
        value=f"{round(user1_time/3600, 1)}h",
        inline=True
    )
    embed.add_field(
        name=user.name,
        value=f"{round(user2_time/3600, 1)}h",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command()
async def duo(ctx, user: discord.Member):
    # Trouver les sessions où les deux utilisateurs étaient dans le même salon
    cursor = db.execute('SELECT * FROM voice_sessions WHERE user_id = ?', (ctx.author.id,))
    user1_sessions = cursor.fetchall()
    cursor = db.execute('SELECT * FROM voice_sessions WHERE user_id = ?', (user.id,))
    user2_sessions = cursor.fetchall()
    
    total_duo_time = 0
    for session1 in user1_sessions:
        for session2 in user2_sessions:
            if (session1[3] == session2[3] and
                session1[4] < session2[5] and
                session2[4] < session1[5]):
                # Calculer le temps de chevauchement
                overlap_start = max(session1[5], session2[5])
                overlap_end = min(session1[6], session2[6])
                total_duo_time += (overlap_end - overlap_start).total_seconds()
    
    hours = round(total_duo_time / 3600, 1)
    await ctx.send(f"Vous avez passé {hours}h en vocal ensemble!")

# Fonction utilitaire pour vérifier les streaks
def get_streak_days(user_id):
    cursor = db.execute('SELECT start_time FROM voice_sessions WHERE user_id = ? ORDER BY start_time', (user_id,))
    sessions = cursor.fetchall()
    days = set()
    current_streak = 0
    best_streak = 0
    last_day = None
    
    for session in sessions:
        day = datetime.fromtimestamp(session[0]).date()
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
    cursor = db.execute('SELECT total_time FROM voice_times WHERE user_id = ?', (ctx.author.id,))
    row = cursor.fetchone()
    
    if row:
        total_minutes = round(row['total_time'] / 60)
        await ctx.send(f"Vous avez passé {total_minutes} minutes en vocal!")
    else:
        await ctx.send("Vous n'avez pas encore passé de temps en vocal!")

@bot.command()
async def top(ctx, limit: int = 5):
    cursor = db.execute('SELECT username, total_time FROM voice_times ORDER BY total_time DESC LIMIT ?', (limit,))
    top_users = cursor.fetchall()
    
    embed = discord.Embed(title=f"Top {limit} - Temps en vocal", color=discord.Color.blue())
    for i, (username, total_time) in enumerate(top_users, 1):
        minutes = round(total_time / 60)
        embed.add_field(
            name=f"#{i} {username}", 
            value=f"{minutes} minutes",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def mes_salons(ctx):
    # Récupérer toutes les sessions de l'utilisateur groupées par salon
    cursor = db.execute('SELECT channel_id, channel_name, SUM(duration), COUNT(*) FROM voice_sessions WHERE user_id = ? GROUP BY channel_id, channel_name ORDER BY SUM(duration) DESC', (ctx.author.id,))
    salons_stats = cursor.fetchall()
    
    embed = discord.Embed(
        title=f"Temps passé par salon pour {ctx.author.name}",
        color=discord.Color.blue()
    )
    
    for salon in salons_stats:
        heures = round(salon[2] / 3600, 1)
        sessions = salon[3]
        embed.add_field(
            name=salon[1],
            value=f"⏰ {heures}h\n🔄 {sessions} sessions",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command()
async def user_temps(ctx, user: discord.Member):
    # Récupérer les stats de l'utilisateur mentionné
    cursor = db.execute('SELECT total_time FROM voice_times WHERE user_id = ?', (user.id,))
    user_data = next(cursor, {'total_time': 0})
    
    if user_data['total_time'] > 0:
        total_minutes = round(user_data['total_time'] / 60)
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
        cursor = db.execute('SELECT SUM(duration) FROM voice_sessions WHERE user_id = ? AND start_time >= ?', (user.id, today))
        today_time = next(cursor, {'SUM(duration)': 0})['SUM(duration)']
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