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


# --- PETIT SERVEUR WEB (POUR RAILWAY/RENDER) ---
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
    self.selected_slots = set()  # Stockera les paires (jour, creneau)

    # Boutons pour les catégories
    for cat in course_data.get("categories", []):
      self.add_item(ItemButton(cat, "cat"))

    # Boutons combinés Jour + Créneau pour un choix précis
    for jour in course_data.get("jours", []):
      for creneau in course_data.get("creneaux", []):
        self.add_item(SlotButton(jour, creneau))

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

    if self.label in view.selected_categories:
      view.selected_categories.remove(self.label)
      self.style = discord.ButtonStyle.secondary
    else:
      view.selected_categories.add(self.label)
      self.style = discord.ButtonStyle.success

    await interaction.response.edit_message(view=view)


class SlotButton(discord.ui.Button):

  def __init__(self, jour: str, creneau: str):
    label = f"{jour} - {creneau}"
    super().__init__(
        label=label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"slot_{jour}_{creneau}",
    )
    self.jour = jour
    self.creneau = creneau

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    pair = (self.jour, self.creneau)

    if pair in view.selected_slots:
      view.selected_slots.remove(pair)
      self.style = discord.ButtonStyle.secondary
    else:
      view.selected_slots.add(pair)
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

    if not view.selected_categories or not view.selected_slots:
      await interaction.response.send_message(
          "⚠️ Tu dois sélectionner au moins une **catégorie** et un"
          " **créneau** !",
          ephemeral=True,
      )
      return

    config = load_json(CONFIG_FILE, {})
    if view.course not in config:
      config[view.course] = {}

    # Nettoyage préalable des anciennes dispos de ce pilote pour cette course
    for cat_k, cat_v in list(config[view.course].items()):
      if isinstance(cat_v, dict):
        for day_k, day_v in list(cat_v.items()):
          if isinstance(day_v, dict):
            for slot_k, slot_pilotes in list(day_v.items()):
              if isinstance(slot_pilotes, list) and view.pilote in slot_pilotes:
                slot_pilotes.remove(view.pilote)

    # Enregistrement précis des paires Jour/Créneau choisies
    for cat in view.selected_categories:
      if cat not in config[view.course]:
        config[view.course][cat] = {}
      for jour, creneau in view.selected_slots:
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

    # --- CONSTRUCTION DU RÉCAPITULATIF GLOBAL ---
    channel = interaction.channel
    if channel:
      ordre_jours_ref = view.course_data.get("jours", [])
      ordre_creneaux_ref = view.course_data.get("creneaux", [])

      embed = discord.Embed(
          title=f"📊 Récapitulatif des Dispos — {view.course}",
          description=f"Mise à jour suite au choix de **{view.pilote}**",
          color=discord.Color.blue(),
      )

      course_data = config[view.course]
      for cat, jours_dict in course_data.items():
        cat_text = ""
        jours_tries = sorted(
            jours_dict.keys(),
            key=lambda x: (
                ordre_jours_ref.index(x) if x in ordre_jours_ref else 99
            ),
        )

        for jour in jours_tries:
          creneaux_dict = jours_dict[jour]
          cat_text += f"📅 **{jour}**\n"

          creneaux_tries = sorted(
              creneaux_dict.keys(),
              key=lambda x: (
                  ordre_creneaux_ref.index(x) if x in ordre_creneaux_ref else 99
              ),
          )

          for creneau in creneaux_tries:
            pilotes = creneaux_dict[creneau]
            if pilotes:
              pilotes_str = ", ".join(pilotes)
              cat_text += f" • `{creneau}` ➔ {pilotes_str}\n"
            else:
              cat_text += f" • `{creneau}` ➔ *Personne*\n"
          cat_text += "\n"

        if cat_text:
          embed.add_field(
              name=f"🏎️ Catégorie : {cat}", value=cat_text, inline=False
          )

      await interaction.followup.send(embed=embed)


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
      if c_key == view.course:
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
  pilotes = load_json(DRIVERS_FILE, [])
  if not isinstance(pilotes, list):
    pilotes = []
  return [
      app_commands.Choice(name=p, value=p)
      for p in pilotes
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


bot.run(os.getenv("DISCORD_TOKEN"))
