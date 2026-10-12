from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
import discord
from discord import app_commands
from discord.ext import commands, tasks

# Configuration des chemins absolus
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config_course.json")
CHAMP_FILE = os.path.join(BASE_DIR, "config_championnat.json")
DRIVERS_FILE = os.path.join(BASE_DIR, "drivers.json")

# Configuration des identifiants (Remplace avec tes vrais identifiants)
SALON_ENTRAINEMENT_ID = 1525497448305393705
ROLE_PILOTE_SPM_ID = 1222995895000371290

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_json(filename, default):
  if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return default
  return default


# --- SERVEUR WEB INTEGRÉ (Pour éviter la mise en veille Railway / Render) ---
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


# --- FONCTION DE GÉNÉRATION DE L'EMBED PRINCIPAL (AVEC TRI CHRONOLOGIQUE) ---
def generate_planning_embed(course: str):
  config = load_json(CONFIG_FILE, {})
  course_data = config.get(course, {})

  embed = discord.Embed(
      title=f"🏎️ Planning des Disponibilités — {course}",
      description=(
          "Voici le récapitulatif en direct des inscrits par catégorie,"
          " créneau et absences.\nClique sur le bouton ci-dessous pour"
          " modifier tes choix !"
      ),
      color=discord.Color.gold(),
  )

  categories = course_data.get("categories", [])
  has_data = False

  # Ordre logique pour trier les jours de la semaine
  ordre_jours = {
      "Lundi": 1,
      "Mardi": 2,
      "Mercredi": 3,
      "Jeudi": 4,
      "Vendredi": 5,
      "Samedi": 6,
      "Dimanche": 7,
      "Général": 8,
  }

  # 1. Traitement des catégories
  for cat in categories:
    cat_content = course_data.get(cat, {})
    lignes_cat = []

    if isinstance(cat_content, dict):
      # Tri des jours selon l'ordre chronologique
      jours_tries = sorted(
          cat_content.keys(), key=lambda j: ordre_jours.get(j, 99)
      )

      for jour in jours_tries:
        creneaux_dict = cat_content[jour]
        if isinstance(creneaux_dict, dict):
          for creneau, pilotes_list in creneaux_dict.items():
            if pilotes_list:
              has_data = True
              pilotes_str = ", ".join(pilotes_list)
              lignes_cat.append(f"• **{jour} - {creneau}** ➔ {pilotes_str}")

    valeur_champ = (
        "\n".join(lignes_cat) if lignes_cat else "Aucun inscrit pour le moment."
    )
    embed.add_field(
        name=f"🏆 Catégorie : {cat}", value=valeur_champ, inline=False
    )

  # 2. Traitement de la section des absents
  absents_list = course_data.get("absents", [])
  if absents_list:
    has_data = True
    absents_str = ", ".join(absents_list)
    embed.add_field(name="❌ Pilotes Absents", value=absents_str, inline=False)
  else:
    embed.add_field(
        name="❌ Pilotes Absents", value="Aucun absent signalé.", inline=False
    )

  if not has_data:
    embed.add_field(
        name="⚠️ Statut",
        value="Aucune disponibilité ni absence enregistrée pour l'instant.",
        inline=False,
    )

  return embed


# --- INTERFACE INTERACTIVE DE SÉLECTION (PRIVÉE) ---
class DispoView(discord.ui.View):

  def __init__(
      self,
      pilote: str,
      course: str,
      course_data: dict,
      public_message: discord.Message = None,
  ):
    super().__init__(timeout=180)
    self.pilote = pilote
    self.course = course
    self.course_data = course_data
    self.public_message = public_message

    self.selected_categories = set()
    self.selected_creneaux = set()

    # Boutons Catégories
    for cat in course_data
