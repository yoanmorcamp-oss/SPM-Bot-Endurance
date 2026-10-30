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

# --- CONFIGURATION DES INTENTS STRICTS ---
intents = discord.Intents()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# --- PETIT SERVEUR WEB POUR UPTIMEROBOT & RENDER ---
class DummyHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"Bot Discord SPM Endurance Actif !")

  def log_message(self, format, *args):
    pass


def run_web_server():
  port = int(os.getenv("PORT", 10000))
  server = HTTPServer(("0.0.0.0", port), DummyHandler)
  server.serve_forever()


# Lancement du serveur web en arrière-plan
threading.Thread(target=run_web_server, daemon=True).start()


def load_json(filename, default):
  if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return default
  return default


def save_json(filename, data):
  with open(filename, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4, ensure_ascii=False)


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
def generate_planning_embed(guild_id: str, course: str):
  config = load_json(CONFIG_FILE, {})
  course_template = config.get(course, {})

  # Récupération des données spécifiques au serveur
  server_data = config.get(guild_id, {}).get(course, {})

  embed = discord.Embed(
      title=f"🏎️ Planning des Disponibilités — {course}",
      description=(
          "Voici le récapitulatif en direct des inscrits par catégorie,"
          " créneau et absences.\nClique sur le bouton ci-dessous pour"
          " modifier tes choix !"
      ),
      color=discord.Color.gold(),
  )

  categories = course_template.get("categories", [])
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
    cat_content = server_data.get(cat, {})
    lignes_cat = []

    if isinstance(cat_content, dict):
      jours_tries = sorted(
          cat_content.keys(), key=lambda j: ordre_jours.get(j, 99)
      )

      for jour in jours_tries:
        creneaux_dict = cat_content[jour]
        if isinstance(creneaux_dict, dict):
          # Tri chronologique des créneaux (13h00 avant 18h00)
          creneaux_tries = sorted(creneaux_dict.keys())
          for creneau in creneaux_tries:
            pilotes_list = creneaux_dict[creneau]
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

  absents_list = server_data.get("absents", [])
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


# --- RAFRAÎCHISSEMENT DU PLANNING ---
async def refresh_public_planning(interaction: discord.Interaction, course: str):
  guild_id = str(interaction.guild_id)
  config = load_json(CONFIG_FILE, {})

  if course not in config:
    return

  channel = interaction.channel
  old_msg_id = config.get(guild_id, {}).get(course, {}).get("message_id")

  if old_msg_id:
    try:
      old_msg = await channel.fetch_message(old_msg_id)
      await old_msg.delete()
    except Exception:
      pass

  embed = generate_planning_embed(guild_id, course)
  view = PublicRegisterView(course)
  new_msg = await channel.send(embed=embed, view=view)

  try:
    await new_msg.pin()
  except Exception as e:
    print(f"Erreur lors du pin : {e}")

  if guild_id not in config:
    config[guild_id] = {}
  if course not in config[guild_id]:
    config[guild_id][course] = {}

  config[guild_id][course]["message_id"] = new_msg.id
  save_json(CONFIG_FILE, config)


# --- INTERFACE INTERACTIVE ---
class DispoView(discord.ui.View):

  def __init__(
      self, pilote: str, course: str, course_data: dict, guild_id: str
  ):
    super().__init__(timeout=180)
    self.pilote = pilote
    self.course = course
    self.course_data = course_data
    self.guild_id = guild_id

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
        self.style = discord.ButtonStyle.secondary
      else:
        view.selected_creneaux.add(self.label)
        self.style = discord.ButtonStyle.success

    await interaction.response.edit_message(view=view)


class ConfirmButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="✅ Valider mes dispos", style=discord.ButtonStyle.primary, row=4
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    guild_id = view.guild_id

    if not view.selected_categories or not view.selected_creneaux:
      await interaction.response.send_message(
          "⚠️ Tu dois sélectionner au moins une catégorie et un créneau"
          " horaire !",
          ephemeral=True,
      )
      return

    config = load_json(CONFIG_FILE, {})
    if guild_id not in config:
      config[guild_id] = {}
    if view.course not in config[guild_id]:
      config[guild_id][view.course] = {}

    c_data = config[guild_id][view.course]

    for sub_k, sub_v in list(c_data.items()):
      if isinstance(sub_v, dict):
        for day_k, day_v in list(sub_v.items()):
          if isinstance(day_v, dict):
            for slot_k, slot_pilotes in list(day_v.items()):
              if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                slot_pilotes.remove(view.pilote)

    if "absents" in c_data and view.pilote in c_data["absents"]:
      c_data["absents"].remove(view.pilote)

    for cat in view.selected_categories:
      if cat not in c_data:
        c_data[cat] = {}

      for item_creneau in view.selected_creneaux:
        if " - " in item_creneau:
          jour, creneau = item_creneau.split(" - ", 1)
        else:
          jour, creneau = "Général", item_creneau

        if jour not in c_data[cat]:
          c_data[cat][jour] = {}
        if creneau not in c_data[cat][jour]:
          c_data[cat][jour][creneau] = []

        if view.pilote not in c_data[cat][jour][creneau]:
          c_data[cat][jour][creneau].append(view.pilote)

    save_json(CONFIG_FILE, config)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content="✅ **Disponibilités enregistrées avec succès !**", view=view
    )
    await refresh_public_planning(interaction, view.course)


class AbsentButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="❌ Signaler mon absence",
        style=discord.ButtonStyle.secondary,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    guild_id = view.guild_id
    config = load_json(CONFIG_FILE, {})

    if guild_id not in config:
      config[guild_id] = {}
    if view.course not in config[guild_id]:
      config[guild_id][view.course] = {}

    c_data = config[guild_id][view.course]

    for sub_k, sub_v in list(c_data.items()):
      if isinstance(sub_v, dict):
        for day_k, day_v in list(sub_v.items()):
          if isinstance(day_v, dict):
            for slot_k, slot_pilotes in list(day_v.items()):
              if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                slot_pilotes.remove(view.pilote)

    if "absents" not in c_data:
      c_data["absents"] = []

    if view.pilote not in c_data["absents"]:
      c_data["absents"].append(view.pilote)

    save_json(CONFIG_FILE, config)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content=f"❌ **Absence enregistrée pour {view.pilote}.**", view=view
    )
    await refresh_public_planning(interaction, view.course)


class ClearButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="🗑️ Effacer mes choix", style=discord.ButtonStyle.danger, row=4
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    guild_id = view.guild_id
    config_data = load_json(CONFIG_FILE, {})

    if guild_id in config_data and view.course in config_data[guild_id]:
      c_data = config_data[guild_id][view.course]
      for sub_k, sub_v in list(c_data.items()):
        if isinstance(sub_v, dict):
          for day_k, day_v in list(sub_v.items()):
            if isinstance(day_v, dict):
              for slot_k, slot_pilotes in list(day_v.items()):
                if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                  slot_pilotes.remove(view.pilote)

      if "absents" in c_data and view.pilote in c_data["absents"]:
        c_data["absents"].remove(view.pilote)

    save_json(CONFIG_FILE, config_data)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content="🗑️ **Tes choix ont été entièrement effacés !**", view=view
    )
    await refresh_public_planning(interaction, view.course)


class PublicRegisterView(discord.ui.View):

  def __init__(self, course: str):
    super().__init__(timeout=None)
    self.course = course

    safe_course_id = course.replace(" ", "_").lower()
    button = discord.ui.Button(
        label="📝 Indiquer / Modifier mes dispos",
        style=discord.ButtonStyle.success,
        custom_id=f"persistent_dispo_{safe_course_id}",
    )
    self.add_item(button)

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    expected_custom_id = f"persistent_dispo_{self.course.replace(' ', '_').lower()}"
    if interaction.data.get("custom_id") == expected_custom_id:
      await interaction.response.defer(ephemeral=True)

      guild_id = str(interaction.guild_id)
      config_data = load_json(CONFIG_FILE, {})

      if self.course not in config_data:
        await interaction.followup.send(
            f"⚠️ La course **{self.course}** est introuvable.", ephemeral=True
        )
        return False

      pilote_pseudo = interaction.user.display_name
      view = DispoView(
          pilote=pilote_pseudo,
          course=self.course,
          course_data=config_data[self.course],
          guild_id=guild_id,
      )

      await interaction.followup.send(
          f"🎛️ **Pilote : {pilote_pseudo}** | Course : **{self.course}**\nFais"
          " tes choix ci-dessous :",
          view=view,
          ephemeral=True,
      )
      return False
    return True


@bot.tree.command(
    name="publier_planning",
    description="Publie et épingle le message officiel de planning pour une course",
)
@app_commands.describe(course="Nom de la course")
async def publier_planning(interaction: discord.Interaction, course: str):
  guild_id = str(interaction.guild_id)
  config_data = load_json(CONFIG_FILE, {})

  if course not in config_data:
    await interaction.response.send_message(
        f"⚠️ La course **{course}** est introuvable dans la configuration.",
        ephemeral=True,
    )
    return

  embed = generate_planning_embed(guild_id, course)
  view = PublicRegisterView(course)

  await interaction.response.send_message(
      f"📌 **Planning publié pour {course} !**", ephemeral=True
  )

  msg = await interaction.followup.send(embed=embed, view=view)

  try:
    await msg.pin()
  except Exception as e:
    print(f"Erreur lors du pin : {e}")

  if guild_id not in config_data:
    config_data[guild_id] = {}
  if course not in config_data[guild_id]:
    config_data[guild_id][course] = {}

  config_data[guild_id][course]["message_id"] = msg.id
  save_json(CONFIG_FILE, config_data)


# --- AUTOCOMPLÉTION ---
@publier_planning.autocomplete("course")
async def publier_course_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
  try:
    course_config = load_json(CONFIG_FILE, {})
    if not isinstance(course_config, dict):
      return []

    courses = [
        k
        for k in course_config.keys()
        if not k.isdigit() and isinstance(course_config[k], dict)
    ]

    choices = [
        app_commands.Choice(name=str(c), value=str(c))
        for c in courses
        if current.lower() in str(c).lower()
    ]
    return choices[:25]
  except Exception as e:
    print(f"Erreur autocomplétion course : {e}")
    return []


@bot.event
async def on_ready():
  if not "RappelChampionnat" in bot.cogs:
    await bot.add_cog(RappelChampionnat(bot))

  courses_config = load_json(CONFIG_FILE, {})
  for course_name, content in courses_config.items():
    if not course_name.isdigit() and isinstance(content, dict):
      bot.add_view(PublicRegisterView(course_name))

  print(f"Bot connecté en tant que {bot.user} !")
  try:
    synced = await bot.tree.sync()
    print(f"Commandes synchronisées : {len(synced)}")
  except Exception as en:
    print(f"Erreur de synchronisation : {en}")


bot.run(os.getenv("DISCORD_TOKEN"))
