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


# --- PETIT SERVEUR WEB ---
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


# --- INTERFACE INTERACTIVE DE SÉLECTION PAR BOUTONS ---
class DispoView(discord.ui.View):

  def __init__(self, pilote: str, course: str, course_data: dict):
    super().__init__(timeout=180)
    self.pilote = pilote
    self.course = course
    self.course_data = course_data

    self.selected_categories = set()
    self.selected_jours = set()
    self.selected_creneaux = set()

    for cat in course_data.get("categories", []):
      self.add_item(ItemButton(cat, "cat"))

    for jour in course_data.get("jours", []):
      self.add_item(ItemButton(jour, "jour"))

    for creneau in course_data.get("creneaux", []):
      self.add_item(ItemButton(creneau, "creneau"))

    self.add_item(ConfirmButton())
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

    elif self.group == "jour":
      if self.label in view.selected_jours:
        view.selected_jours.remove(self.label)
        self.style = discord.ButtonStyle.secondary
      else:
        view.selected_jours.add(self.label)
        self.style = discord.ButtonStyle.success

    elif self.group == "creneau":
      if self.label in view.selected_creneaux:
        view.selected_creneaux.remove(self.label)
        self.style = discord.ButtonStyle.secondary
      else:
        view.selected_creneaux.add(self.label)
        self.style = discord.ButtonStyle.success

    await interaction.response.edit_message(view=view)


class ConfirmButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="✅ Valider mes dispos",
        style=discord.ButtonStyle.primary,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view

    if not view.selected_categories or not view.selected_jours or not view.selected_creneaux:
      await interaction.response.send_message(
          "⚠️ Tu dois sélectionner au moins une catégorie, un jour et un créneau !",
          ephemeral=True,
      )
      return

    config = load_json(CONFIG_FILE, {})
    if view.course not in config:
      config[view.course] = {}

    for cat in view.selected_categories:
      if cat not in config[view.course]:
        config[view.course][cat] = {}
      for jour in view.selected_jours:
        if jour not in config[view.course][cat]:
          config[view.course][cat][jour] = {}
        for creneau in view.selected_creneaux:
          if creneau not in config[view.course][cat][jour]:
            config[view.course][cat][jour][creneau] = []
          if view.pilote not in config[view.course][cat][jour][creneau]:
            config[view.course][cat][jour][creneau].append(view.pilote)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config, f, indent=4, ensure_ascii=False)

    for child in view.children:
      child.disabled = True
    await interaction.response.edit_message(
        content="✅ **Disponibilités enregistrées avec succès !**", view=view
    )

    channel = interaction.channel
    if channel:
      cats_str = ", ".join(view.selected_categories)

      ordre_jours_ref = view.course_data.get("jours", [])
      jours_tires = sorted(
          view.selected_jours,
          key=lambda x: (
              ordre_jours_ref.index(x) if x in ordre_jours_ref else 99
          ),
      )
      jours_str = ", ".join(jours_tires)

      ordre_creneaux_ref = view.course_data.get("creneaux", [])
      creneaux_tires = sorted(
          view.selected_creneaux,
          key=lambda x: (
              ordre_creneaux_ref.index(x) if x in ordre_creneaux_ref else 99
          ),
      )
      creneaux_
