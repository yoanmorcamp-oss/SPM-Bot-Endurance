from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
import discord
from discord import app_commands
from discord.ext import commands, tasks

# Configuration des identifiants (IDs de ton salon et de ton rôle)
SALON_ENTRAINEMENT_ID = 1525497448305393705
ROLE_PILOTE_SPM_ID = 1222995895000371290

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

CONFIG_FILE = "config_course.json"
CHAMP_FILE = "config_championnat.json"


def load_json(filename, default):
  if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return default
  return default


# --- PETIT SERVEUR WEB POUR RENDRE HEUREUX RENDER ---
class DummyHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"Bot Discord SPM Actif !")

  def log_message(self, format, *args):
    pass


def run_web_server():
  port = int(os.getenv("PORT", 10000))
  server = HTTPServer(("0.0.0.0", port), DummyHandler)
  server.serve_forever()


# Lancement du serveur web en arrière-plan (pour Render)
threading.Thread(target=run_web_server, daemon=True).start()


# --- GESTIONNAIRE DE RAPPEL AUTOMATIQUE CHAMPIONNAT ---
class RappelChampionnat(commands.Cog):

  def __init__(self, bot):
    self.bot = bot
    self.rappel_entrainement_champ.start()

  def cog_unload(self):
    self.rappel_entrainement_champ.cancel()

  @tasks.loop(hours=24)
  async def rappel_entrainement_champ(self):
    now_date = datetime.now().strftime("%Y-%m#%%d")
    champ_config = load_json(CHAMP_FILE, {})

    for course, data in champ_config.items():
      if data.get("date_entrainement") == now_date:
        channel = self.bot.get_channel(SALON_ENTRAINEMENT_ID)
        if channel:
          role_mention = f"<@&{ROLE_PILOTE_SPM_ID}>"
          embed = discord.Embed(
              title="🔔 Rappel Entraînement LMXGT — Ce soir !",
              description=(
                  f"Salut l'équipe ! Session d'entraînement ce soir pour"
                  f" préparer la manche de **{course}** de ce dimanche.\n\nVenez"
                  " tester vos setups et rouler un peu ! 🏎️💨"
              ),
              color=discord.Color.blue(),
          )
          await channel.send(
              content=f"{role_mention} Rappel entraînement !", embed=embed
          )

  @rappel_entrainement_champ.before_loop
  async def before_rappel_entrainement(self):
    await self.bot.wait_until_ready()


# --- COMMANDE SLASH DISPO & AUTOCOMPLÉTIONS ---
@bot.tree.command(
    name="dispo", description="Indiquer ses disponibilités pour une course"
)
@app_commands.describe(
    pilote="Sélectionne ton nom", course="Nom de la course"
)
async def dispo(interaction: discord.Interaction, pilote: str, course: str):
  config = load_json(CONFIG_FILE, {})
  if course not in config:
    config[course] = {}
  config[course][pilote] = "Enregistré"
  with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4, ensure_ascii=False)

  await interaction.response.send_message(
      f"✅ Disponibilité enregistrée pour **{pilote}** sur la course"
      f" **{course}** !",
      ephemeral=True,
  )


@dispo.autocomplete("pilote")
async def dispo_pilote_autocomplete(
    interaction: discord.Interaction, current: str
):
  pilotes = []
  if interaction.guild:
    role = interaction.guild.get_role(ROLE_PILOTE_SPM_ID)
    if role:
      pilotes = [member.display_name for member in role.members]
  if not pilotes:
    pilotes = ["Pilote Stinger"]
  return [
      app_commands.Choice(name=p, value=p)
      for p in pilotes
      if current.lower() in p.lower()
  ][:25]


@dispo.autocomplete("course")
async def dispo_course_autocomplete(
    interaction: discord.Interaction, current: str
):
  champ_config = load_json(CHAMP_FILE, {})
  courses = list(champ_config.keys())
  if not courses:
    courses = ["6 Heures de Fuji", "Le Mans", "Spa-Francorchamps"]
  return [
      app_commands.Choice(name=c, value=c)
      for c in courses
      if current.lower() in c.lower()
  ][:25]


@bot.event
async def on_ready():
  if not "RappelChampionnat" in bot.cogs:
    await bot.add_cog(RappelChampionnat(bot))

  print(f"Bot connecté en tant que {bot.user} !")
  try:
    synced = await bot.tree.sync()
    print(f"Commandes slash synchronisées : {len(synced)}")
  except Exception as e:
    print(e)


# Lancement sécurisé du bot via variable d'environnement
bot.run(os.getenv("DISCORD_TOKEN"))
