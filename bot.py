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
      "24 octobre": 8,
      "25 octobre": 9,
      "26 octobre": 10,
      "Général": 11,
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
    for cat in course_data.get("categories", []):
      self.add_item(ItemButton(cat, "cat"))

    # Boutons Créneaux combinés Jour + Heure
    jours = course_data.get("jours", [])
    creneaux = course_data.get("creneaux", [])
    for jour in jours:
      for creneau in creneaux:
        label_btn = f"{jour} - {creneau}"
        self.add_item(ItemButton(label_btn, "creneau"))

    # Boutons d'action
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

    # Retrait de la liste des absents si le pilote était marqué absent
    if (
        "absents" in config[view.course]
        and view.pilote in config[view.course]["absents"]
    ):
      config[view.course]["absents"].remove(view.pilote)

    for cat in view.selected_categories:
      if cat not in config[view.course]:
        config[view.course][cat] = {}

      for item_creneau in view.selected_creneaux:
        if " - " in item_creneau:
          jour, creneau = item_creneau.split(" - ", 1)
        else:
          jour, creneau = "Général", item_creneau

        if jour not in config[view.course][cat]:
          config[view.course][cat][jour] = {}
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

    if view.public_message:
      new_embed = generate_planning_embed(view.course)
      await view.public_message.edit(embed=new_embed)


class AbsentButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="❌ Signaler mon absence",
        style=discord.ButtonStyle.secondary,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    config = load_json(CONFIG_FILE, {})

    if view.course not in config:
      config[view.course] = {}

    # Retrait du pilote de tous les créneaux validés
    c_data = config[view.course]
    for sub_k, sub_v in list(c_data.items()):
      if isinstance(sub_v, dict):
        for day_k, day_v in list(sub_v.items()):
          if isinstance(day_v, dict):
            for slot_k, slot_pilotes in list(day_v.items()):
              if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                slot_pilotes.remove(view.pilote)

    # Ajout du pilote dans la liste des absents
    if "absents" not in config[view.course]:
      config[view.course]["absents"] = []

    if view.pilote not in config[view.course]["absents"]:
      config[view.course]["absents"].append(view.pilote)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config, f, indent=4, ensure_ascii=False)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content=f"❌ **Absence enregistrée pour {view.pilote}.**", view=view
    )

    if view.public_message:
      new_embed = generate_planning_embed(view.course)
      await view.public_message.edit(embed=new_embed)


class ClearButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="🗑️ Effacer mes choix",
        style=discord.ButtonStyle.danger,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    config_data = load_json(CONFIG_FILE, {})

    if view.course in config_data:
      c_data = config_data[view.course]
      # Retrait des créneaux
      for sub_k, sub_v in list(c_data.items()):
        if isinstance(sub_v, dict):
          for day_k, day_v in list(sub_v.items()):
            if isinstance(day_v, dict):
              for slot_k, slot_pilotes in list(day_v.items()):
                if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                  slot_pilotes.remove(view.pilote)

      # Retrait des absents
      if "absents" in c_data and view.pilote in c_data["absents"]:
        c_data["absents"].remove(view.pilote)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
      json.dump(config_data, f, indent=4, ensure_ascii=False)

    for child in view.children:
      child.disabled = True

    await interaction.response.edit_message(
        content="🗑️ **Tes choix ont été entièrement effacés !**", view=view
    )

    if view.public_message:
      new_embed = generate_planning_embed(view.course)
      await view.public_message.edit(embed=new_embed)


# --- BOUTON PERSISTANT SUR LE MESSAGE PUBLIC (AVEC ACCUSÉ DE RÉCEPTION RAPIDE) ---
class PublicRegisterView(discord.ui.View):

  def __init__(self, course: str):
    super().__init__(timeout=None)
    self.course = course

    safe_course_id = course.replace(" ", "_").lower()
    self.add_item(
        discord.ui.Button(
            label="📝 Indiquer / Modifier mes dispos",
            style=discord.ButtonStyle.success,
            custom_id=f"persistent_dispo_{safe_course_id}",
        )
    )

  async def interaction_check(self, interaction: discord.Interaction) -> bool:
    expected_custom_id = f"persistent_dispo_{self.course.replace(' ', '_').lower()}"
    if interaction.data.get("custom_id") == expected_custom_id:
      # Accusé de réception immédiat pour éviter le timeout de Discord
      await interaction.response.defer(ephemeral=True)

      config_data = load_json(CONFIG_FILE, {})
      if self.course not in config_data:
        await interaction.followup.send(
            f"⚠️ La course **{self.course}** est introuvable.",
            ephemeral=True,
        )
        return False

      pilote_pseudo = interaction.user.display_name
      public_message = interaction.message

      view = DispoView(
          pilote=pilote_pseudo,
          course=self.course,
          course_data=config_data[self.course],
          public_message=public_message,
      )

      await interaction.followup.send(
          f"🎛️ **Pilote : {pilote_pseudo}** | Course : **{self.course}**\nFais"
          " tes choix ci-dessous :",
          view=view,
          ephemeral=True,
      )
      return False
    return True


# --- COMMANDE PUBLIER / PLANNING ---
@bot.tree.command(
    name="publier_planning",
    description="Publie et épingle le message officiel de planning pour une course",
)
@app_commands.describe(course="Nom de la course
