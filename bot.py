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

# Configuration des identifiants
SALON_ENTRAINEMENT_ID = 1525497448305393705
ROLE_PILOTE_SPM_ID = 1222995895000371290

# --- CONFIGURATION DES INTENTS (Sécurisé pour Render) ---
intents = discord.Intents.default()
intents.members = False
intents.presences = False
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_json(filename, default):
  if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return default
  return default


# --- SERVEUR WEB INTÉGRÉ (Pour UptimeRobot) ---
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


# --- FONCTION DE GÉNÉRATION DE L'EMBED PRINCIPAL ---
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

  ordre_jours = {
      "Lundi": 1,
      "Mardi": 2,
      "Mercredi": 3,
      "Jeudi": 4,
      "Vendredi": 5,
      "Samedi": 6,
      "Dimanche": 7,
      "30 octobre": 8,
      "31 octobre": 9,
      "1er novembre": 10,
      "23 octobre": 11,
      "24 octobre": 12,
      "25 octobre": 13,
      "26 octobre": 14,
      "Général": 15,
  }

  for cat in categories:
    cat_content = course_data.get(cat, {})
    lignes_cat = []

    if isinstance(cat_content, dict):
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


# --- FONCTION UTILITAIRE POUR RAFRAÎCHIR LE PLANNING EN BAS DU SALON ---
async def refresh_public_planning(interaction: discord.Interaction, course: str):
  config = load_json(CONFIG_FILE, {})
  if course not in config:
    return

  channel = interaction.channel
  old_msg_id = config[course].get("message_id")

  # Suppression de l'ancien message public s'il existe
  if old_msg_id:
    try:
      old_msg = await channel.fetch_message(old_msg_id)
      await old_msg.delete()
    except Exception:
      pass

  # Envoi du nouveau message mis à jour tout en bas
  embed = generate_planning_embed(course)
  view = PublicRegisterView(course)
  new_msg = await channel.send(embed=embed, view=view)

  try:
    await new_msg.pin()
  except Exception as e:
    print(f"Erreur lors du pin : {e}")

  config[course]["message_id"] = new_msg.id
  with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=4, ensure_ascii=False)


# --- INTERFACE INTERACTIVE DE SÉLECTION ---
class DispoView(discord.ui.View):

  def __init__(self, pilote: str, course: str, course_data: dict):
    super().__init__(timeout=180)
    self.pilote = pilote
    self.course = course
    self.course_data = course_data

    self.selected_categories = set()
    self.selected_creneaux = set()

    for cat in course_data.get("categories", []):
      self.add_item(ItemButton(cat, "cat"))

    if course == "24H du Mans":
      mapping_mans = {"23 octobre": "13h00", "24 octobre": "15h30"}
      for jour, creneau in mapping_mans.items():
        label_btn = f"{jour} - {creneau}"
        self.add_item(ItemButton(label_btn, "creneau"))
    else:
      jours = course_data.get("jours", [])
      creneaux = course_data.get("creneaux", [])
      for jour in jours:
        for creneau in creneaux:
          label_btn = f"{jour} - {creneau}"
          self.add_item(ItemButton(label_btn, "creneau"))

    self.add_item(ConfirmButton())
    self.add_item(AbsentButton())
    self.add_item(ClearButton())


class ItemButton(discord.ui.Button):

  def __init__(self, label: str, group: str):
    super().__init__(
        label=label, style=discord.ButtonStyle.secondary, custom_id=f"{group}_{label}"
    )
    self.group = group

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view

    if self.group == "cat":
      if self.label in view.selected_categories:
        view.selected_categories.remove(self.label)
        self.style = discord.ButtonStyle.secondary
      else:
        view.selected_categories.add(self.label)
        self.style = discord.ButtonStyle.success

    elif self.group == "creneau":
      if self.label in view.selected_creneaux:
        view.selected_creneaux.remove(self.label)
        self.style = discord.ButtonStyle
