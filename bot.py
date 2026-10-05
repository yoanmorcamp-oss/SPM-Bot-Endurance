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
DRIVERS_FILE = "drivers.json"


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
    now_date = datetime.now().strftime("%Y-%m-%d")
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
    pilote="Sélectionne ton nom (ou 🗑️ Effacer mes dispos)",
    course="Nom de la course",
    categorie="Catégorie de véhicule",
    jour="Jour de l'événement",
    creneaux="Créneau horaire",
)
async def dispo(
    interaction: discord.Interaction,
    pilote: str,
    course: str,
    categorie: str,
    jour: str,
    creneaux: str,
):
  config = load_json(CONFIG_FILE, {})

  # Gestion de la suppression des disponibilités
  if pilote == "🗑️ Effacer mes dispos":
    # On parcourt la structure pour nettoyer le nom du joueur partout où il se trouve
    supprimé = False
    for c_key, c_data in config.items():
      if isinstance(c_data, dict):
        for sub_k, sub_v in list(c_data.items()):
          if isinstance(sub_v, dict):
            for day_k, day_v in list(sub_v.items()):
              if isinstance(day_v, dict):
                for slot_k, slot_pilotes in list(day_v.items()):
                  if (
                      isinstance(slot_pilotes, list)
                      and interaction.user.display_name in slot_pilotes
                  ):
                    slot_pilotes.remove(interaction.user.display_name)
                    supprimé = True

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config, f, indent=4, ensure_ascii=False)

    await interaction.response.send_message(
        "🗑️ Tes disponibilités ont été effacées avec succès.", ephemeral=True
    )
    return

  # Structure attendue dans CONFIG_FILE : course -> catégorie -> jour -> créneau -> [liste de pilotes]
  if course not in config:
    config[course] = {}
  if categorie not in config[course]:
    config[course][categorie] = {}
  if jour not in config[course][categorie]:
    config[course][categorie][jour] = {}
  if creneaux not in config[course][categorie][jour]:
    config[course][categorie][jour][creneaux] = []

  # Ajout du pilote s'il n'y est pas déjà
  if pilote not in config[course][categorie][jour][creneaux]:
    config[course][categorie][jour][creneaux].append(pilote)

  with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4, ensure_ascii=False)

  # Réponse éphémère à l'utilisateur
  await interaction.response.send_message(
      f"✅ Disponibilité enregistrée pour **{pilote}** sur **{course}** ("
      f"**{categorie}** - **{jour}** à **{creneaux}**) !",
      ephemeral=True,
  )

  # Envoi du message automatique formaté dans le salon (comme sur ton modèle)
  channel = interaction.channel
  if channel:
    embed = discord.Embed(
        title=f"🏎️ Planning - {course}",
        description=(
            f"📅 **{jour}**\nCatégorie : **{categorie}**\n• **{creneaux}** ➔"
            f" **{pilote}**"
        ),
        color=discord.Color.blue(),
    )
    await channel.send(embed=embed)


@dispo.autocomplete("pilote")
async def dispo_pilote_autocomplete(
    interaction: discord.Interaction, current: str
):
  pilotes = load_json(DRIVERS_FILE, [])
  if not isinstance(pilotes, list):
    pilotes = []

  # Ajout de l'option poubelle pour effacer ses infos
  options = ["🗑️ Effacer mes dispos"] + pilotes

  return [
      app_commands.Choice(name=p, value=p)
      for p in options
      if current.lower() in p.lower()
  ][:25]


@dispo.autocomplete("course")
async def dispo_course_autocomplete(
    interaction: discord.Interaction, current: str
):
  course_config = load_json(CONFIG_FILE, {})
  courses = list(course_config.keys())

  return [
      app_commands.Choice(name=c, value=c)
      for c in courses
      if current.lower() in c.lower()
  ][:25]


@dispo.autocomplete("categorie")
async def dispo_categorie_autocomplete(
    interaction: discord.Interaction, current: str
):
  # Récupère la course sélectionnée dynamiquement dans l'interaction
  course_selected = interaction.namespace.course
  course_config = load_json(CONFIG_FILE, {})

  categories = []
  if course_selected in course_config:
    categories = course_config[course_selected].get("categories", [])

  return [
      app_commands.Choice(name=cat, value=cat)
      for cat in categories
      if current.lower() in cat.lower()
  ][:25]


@dispo.autocomplete("jour")
async def dispo_jour_autocomplete(
    interaction: discord.Interaction, current: str
):
  course_selected = interaction.namespace.course
  course_config = load_json(CONFIG_FILE, {})

  jours = []
  if course_selected in course_config:
    jours = course_config[course_selected].get("jours", [])

  return [
      app_commands.Choice(name=j, value=j)
      for j in jours
      if current.lower() in j.lower()
  ][:25]


@dispo.autocomplete("creneaux")
async def dispo_creneaux_autocomplete(
    interaction: discord.Interaction, current: str
):
  course_selected = interaction.namespace.course
  course_config = load_json(CONFIG_FILE, {})

  creneaux = []
  if course_selected in course_config:
    creneaux = course_config[course_selected].get("creneaux", [])

  return [
      app_commands.Choice(name=cr, value=cr)
      for cr in creneaux
      if current.lower() in cr.lower()
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
