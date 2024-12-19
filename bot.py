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
    cursor = db.execute('''
        SELECT SUM(duration) as total_time 
        FROM voice_sessions 
        WHERE user_id = ? AND start_time >= ?
    ''', (ctx.author.id, today))
    
    row = cursor.fetchone()
    total_time = row['total_time'] if row and row['total_time'] else 0
    minutes = round(total_time / 60)
    
    await ctx.send(f"Aujourd'hui, vous avez passé {minutes} minutes en vocal!")

@bot.command()
async def stats_semaine(ctx):
    week_ago = datetime.now() - timedelta(days=7)
    cursor = db.execute('''
        SELECT strftime('%w', start_time) as day, SUM(duration) as total_time
        FROM voice_sessions 
        WHERE user_id = ? AND start_time >= ?
        GROUP BY day
        ORDER BY day
    ''', (ctx.author.id, week_ago))
    
    daily_times = defaultdict(int)
    days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
    
    for row in cursor:
        day_num = int(row['day'])
        daily_times[days[day_num]] = row['total_time']
    
    embed = discord.Embed(title="Statistiques hebdomadaires", color=discord.Color.blue())
    for day in days:
        minutes = round(daily_times[day] / 60)
        embed.add_field(name=day, value=f"{minutes} minutes", inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def stats_mois(ctx):
    month_ago = datetime.now() - timedelta(days=30)
    cursor = db.execute('''
        SELECT SUM(duration) as total_time 
        FROM voice_sessions 
        WHERE user_id = ? AND start_time >= ?
    ''', (ctx.author.id, month_ago))
    row = cursor.fetchone()
    total_time = row['total_time'] if row and row['total_time'] else 0
    hours = round(total_time / 3600, 1)
    
    await ctx.send(f"Ce mois-ci, vous avez passé {hours} heures en vocal!")

@bot.command()
async def moyenne(ctx):
    cursor = db.execute('''
        SELECT date(start_time) as day, SUM(duration) as daily_time
        FROM voice_sessions 
        WHERE user_id = ?
        GROUP BY day
    ''', (ctx.author.id,))
    
    rows = cursor.fetchall()
    if rows:
        total_time = sum(row['daily_time'] for row in rows)
        avg_time = total_time / len(rows)
        await ctx.send(f"En moyenne, vous passez {round(avg_time/60)} minutes par jour en vocal!")
    else:
        await ctx.send("Pas encore assez de données pour calculer une moyenne!")

@bot.command()
async def top_salon(ctx):
    cursor = db.execute('''
        SELECT channel_name, SUM(duration) as total_time, COUNT(*) as sessions
        FROM voice_sessions 
        WHERE user_id = ? 
        GROUP BY channel_name 
        ORDER BY total_time DESC
    ''', (ctx.author.id,))
    
    embed = discord.Embed(title="Temps par salon", color=discord.Color.green())
    for row in cursor:
        hours = round(row['total_time'] / 3600, 1)
        sessions = row['sessions']
        embed.add_field(
            name=row['channel_name'],
            value=f"⏰ {hours}h\n🔄 {sessions} sessions",
            inline=False
        )
    
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
    cursor = db.execute('''
        SELECT s1.channel_id, s1.start_time, s1.end_time, s2.start_time, s2.end_time
        FROM voice_sessions s1
        JOIN voice_sessions s2 ON s1.channel_id = s2.channel_id
        WHERE s1.user_id = ? AND s2.user_id = ?
        AND s1.end_time > s2.start_time AND s2.end_time > s1.start_time
    ''', (ctx.author.id, user.id))
    
    total_duo_time = 0
    for row in cursor:
        overlap_start = max(row[1], row[3])
        overlap_end = min(row[2], row[4])
        total_duo_time += (overlap_end - overlap_start).total_seconds()
    
    hours = round(total_duo_time / 3600, 1)
    await ctx.send(f"Vous avez passé {hours}h en vocal ensemble!")

# Fonction utilitaire pour vérifier les streaks
def get_streak_days(user_id):
    cursor = db.execute('''
        SELECT DISTINCT date(start_time) as day
        FROM voice_sessions
        WHERE user_id = ?
        ORDER BY day
    ''', (user_id,))
    
    days = [row['day'] for row in cursor.fetchall()]
    if not days:
        return 0, 0
        
    current_streak = 1
    best_streak = 1
    current_count = 1
    
    for i in range(1, len(days)):
        date1 = datetime.strptime(days[i-1], '%Y-%m-%d')
        date2 = datetime.strptime(days[i], '%Y-%m-%d')
        if (date2 - date1).days == 1:
            current_count += 1
            current_streak = max(current_streak, current_count)
        else:
            best_streak = max(best_streak, current_count)
            current_count = 1
    
    best_streak = max(best_streak, current_count)
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