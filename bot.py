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
    self.selected_creneaux = (
        set()
    )  # Stocke directement les choix ex: "Samedi - 12h00"

    # 1. Boutons Catégories
    for cat in course_data.get("categories", []):
      self.add_item(ItemButton(cat, "cat"))

    # 2. Boutons combinés Jour + Créneau (ex: "Samedi - 12h00")
    jours = course_data.get("jours", [])
    creneaux = course_data.get("creneaux", [])
    for jour in jours:
      for creneau in creneaux:
        label_btn = f"{jour} - {creneau}"
        self.add_item(ItemButton(label_btn, "creneau"))

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

    if not view.selected_categories or not view.selected_creneaux:
      await interaction.response.send_message(
          "⚠️ Tu dois sélectionner au moins une catégorie et un créneau horaire !",
          ephemeral=True,
      )
      return

    config = load_json(CONFIG_FILE, {})
    if view.course not in config:
      config[view.course] = {}

    for cat in view.selected_categories:
      if cat not in config[view.course]:
        config[view.course][cat] = {}

      for item_creneau in view.selected_creneaux:
        # Découpage propre de "Jour - Heure" (ex: "Samedi - 12h00")
        if " - " in item_creneau:
          jour, creneau = item_creneau.split(" - ", 1)
        else:
          jour, creneau = "Général", item_creneau

        if jour not in config[view.course][cat]:
          config[view.course][cat][jour] = {}
        if creneau not in config[view.course][cat][jour]:
          config[view.course][cat][jour][creneau] = []

        # Ajout du pilote s'il n'y est pas déjà pour ce créneau précis
        if view.pilote not in config[view.course][cat][jour][creneau]:
          config[view.course][cat][jour][creneau].append(view.pilote)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config, f, indent=4, ensure_ascii=False)

    for child in view.children:
      child.disabled = True
    await interaction.response.edit_message(
        content="✅ **Disponibilités enregistrées avec succès !**", view=view
    )

    # Envoi du message automatique récapitulatif dans le salon public avec groupement des pilotes
    channel = interaction.channel
    if channel:
      cats_str = ", ".join(view.selected_categories)

      lignes_recap = []
      course_data_actuelle = config.get(view.course, {})

      for cat in view.selected_categories:
        cat_dict = course_data_actuelle.get(cat, {})
        for jour, creneaux_dict in cat_dict.items():
          for creneau, pilotes_list in creneaux_dict.items():
            if pilotes_list:
              pilotes_str = ", ".join(pilotes_list)
              lignes_recap.append(
                  f"• **{jour} - {creneau}** ({cat}) ➔ {pilotes_str}"
              )

      recap_texte = (
          "\n".join(lignes_recap)
          if lignes_recap
          else "Aucun créneau enregistré."
      )

      embed = discord.Embed(
          title=f"🏎️ Mise à jour des disponibilités — {view.course}",
          description=(
              f"Le pilote **{view.pilote}** vient de mettre à jour ses"
              f" choix !\nCatégorie(s) : **{cats_str}**\n\n**Planning"
              f" actuel :**\n{recap_texte}"
          ),
          color=discord.Color.green(),
      )
      await channel.send(embed=embed)


class ClearButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="🗑️ Effacer mes dispos",
        style=discord.ButtonStyle.danger,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    config_data = load_json(CONFIG_FILE, {})

    for c_key, c_data in config_data.items():
      if isinstance(c_data, dict):
        for sub_k, sub_v in list(c_data.items()):
          if isinstance(sub_v, dict):
            for day_k, day_v in list(sub_v.items()):
              if isinstance(day_v, dict):
                for slot_k, slot_pilotes in list(day_v.items()):
                  if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                    slot_pilotes.remove(view.pilote)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config_data, f, indent=4, ensure_ascii=False)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content="🗑️ **Tes disponibilités ont été entièrement effacées avec succès !**",
        view=view,
    )

    embed = discord.Embed(
        title=f"🗑️ Planning mis à jour — {view.course}",
        description=(
            f"Le pilote **{view.pilote}** a **effacé toutes ses"
            " disponibilités** pour cette course."
        ),
        color=discord.Color.red(),
    )
    await interaction.followup.send(embed=embed)


# --- COMMANDE SLASH DISPO ---
@bot.tree.command(
    name="dispo", description="Indiquer ses disponibilités pour une course"
)
@app_commands.describe(
    pilote="Sélectionne ton nom", course="Nom de la course"
)
async def dispo(interaction: discord.Interaction, pilote: str, course: str):
  config_data = load_json(CONFIG_FILE, {})

  if course not in config_data:
    await interaction.response.send_message(
        f"⚠️ La course **{course}** est introuvable dans la configuration.",
        ephemeral=True,
    )
    return

  view = DispoView(pilote=pilote, course=course, course_data=config_data[course])
  await interaction.response.send_message(
      f"🎛️ **Pilote : {pilote}** | Course : **{course}**\nClique sur les"
      " éléments pour les activer (**vert**), puis clique sur **Valider** ou"
      " **Effacer** :",
      view=view,
      ephemeral=True,
  )


@dispo.autocomplete("pilote")
async def dispo_pilote_autocomplete(
    interaction: discord.Interaction, current: str
):
  try:
    data = load_json(DRIVERS_FILE, [])
    pilotes = []
    if isinstance(data, list):
      pilotes = data
    elif isinstance(data, dict):
      for val in data.values():
        if isinstance(val, list):
          pilotes.extend(val)

    return [
        app_commands.Choice(name=str(p), value=str(p))
        for p in pilotes
        if current.lower() in str(p).lower()
    ][:25]
  except Exception as e:
    print(f"Erreur dans l'autocomplétion pilote : {e}")
    return []


@dispo.autocomplete("course")
async def dispo_course_autocomplete(
    interaction: discord.Interaction, current: str
):
  try:
    course_config = load_json(CONFIG_FILE, {})
    if not isinstance(course_config, dict):
      course_config = {}
    courses = list(course_config.keys())
    return [
        app_commands.Choice(name=str(c), value=str(c))
        for c in courses
        if current.lower() in str(c).lower()
    ][:25]
  except Exception as e:
    print(f"Erreur dans l'autocomplétion course : {e}")
    return []


@bot.event
async def on_ready():
  if not "RappelChampionnat" in bot.cogs:
    await bot.add_cog(RappelChampionnat(bot))

  print(f"Bot connecté en tant que {bot.user} !")
  try:
    # Mets l'ID de ton serveur Discord ici pour une synchro instantanée
    GUILD_ID = discord.Object(id=123456789012345678)  # <--- ID DU SERVEUR

    bot.tree.copy_global_to(guild=GUILD_ID)
    synced = await bot.tree.sync(guild=GUILD_ID)
    print(f"Commandes slash synchronisées sur le serveur : {len(synced)}")
  except Exception as e:
    print(e)


bot.run(os.getenv("DISCORD_TOKEN"))
