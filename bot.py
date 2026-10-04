from datetime import datetime
import json
import os
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

DRIVERS_FILE = "drivers.json"
CONFIG_FILE = "config_course.json"
DISPOS_FILE = "dispos.json"

# ID de ton serveur Discord pour une synchro instantanée
MY_GUILD_ID = discord.Object(id=1222994281334177842)


def load_json(filename, default_val):
  if os.path.exists(filename):
    with open(filename, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return default_val
  return default_val


def save_json(filename, data):
  with open(filename, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


# Ordre logique pour le tri des jours
JOURS_ORDRE = {"vendredi": 1, "samedi": 2, "dimanche": 3}


def trier_dispos(dispos):
  def cle_tri(d):
    jour_val = JOURS_ORDRE.get(d["jour"].lower(), 99)
    creneau_str = d["creneau"].lower().replace("h", ".")
    try:
      creneau_val = float(creneau_str)
    except ValueError:
      creneau_val = 0.0
    return (
        d.get("course", ""),
        d["categorie"],
        jour_val,
        creneau_val,
        d["driver"],
    )

  return sorted(dispos, key=cle_tri)


@bot.event
async def on_ready():
  print(f"Bot connecté et prêt en tant que {bot.user}")
  try:
    bot.tree.clear_commands(guild=MY_GUILD_ID)
    bot.tree.copy_global_to(guild=MY_GUILD_ID)
    synced = await bot.tree.sync(guild=MY_GUILD_ID)
    print(f"Commandes synchronisées sur ton serveur : {len(synced)}")
  except Exception as e:
    print(e)


# --- FONCTION POUR GÉNÉRER L'EMBED DU PLANNING D'UNE COURSE ---
def generate_planning_embed(nom_course):
  dispos = load_json(DISPOS_FILE, [])
  dispos = trier_dispos(dispos)

  embed = discord.Embed(
      title=f"🏎️ Planning - {nom_course}", color=discord.Color.blue()
  )

  dispos_course = [
      d for d in dispos if d.get("course", "").lower() == nom_course.lower()
  ]

  if not dispos_course:
    embed.description = f"Aucune disponibilité enregistrée pour **{nom_course}**."
    return embed

  struct = {}
  for d in dispos_course:
    j = d["jour"]
    cat = d["categorie"]
    creneau = d["creneau"]
    pilote = d["driver"]

    if j not in struct:
      struct[j] = {}
    if cat not in struct[j]:
      struct[j][cat] = {}
    if creneau not in struct[j][cat]:
      struct[j][cat][creneau] = []
    struct[j][cat][creneau].append(pilote)

  for jour, cats in struct.items():
    texte_jour = ""
    for cat, creneaux in cats.items():
      texte_jour += f"__**Catégorie : {cat}**__\n"
      for creneau, pilotes in creneaux.items():
        pilotes_str = ", ".join(pilotes)
        texte_jour += f"• `{creneau}` ➔ **{pilotes_str}**\n"
      texte_jour += "\n"

    embed.add_field(name=f"📅 {jour}", value=texte_jour[:1024], inline=False)

  return embed


# --- VUE INTERACTIVE AVEC BOUTONS MULTIPLES ---
class DispoView(discord.ui.View):

  def __init__(
      self,
      pilote: str,
      course: str,
      categories: list,
      jours: list,
      creneaux: list,
  ):
    super().__init__(timeout=180)
    self.pilote = pilote
    self.course = course
    self.selected_categories = set()
    self.selected_jours = set()
    self.selected_creneaux = set()

    for cat in categories:
      self.add_item(CategoryButton(cat))
    for jour in jours:
      self.add_item(DayButton(jour))
    for creneau in creneaux:
      self.add_item(CreneauButton(creneau))

    # Boutons d'action en bas (Valider et Reset)
    self.add_item(ConfirmButton())
    self.add_item(ResetButton())


class CategoryButton(discord.ui.Button):

  def __init__(self, categorie: str):
    super().__init__(
        label=categorie,
        style=discord.ButtonStyle.secondary,
        custom_id=f"cat_{categorie}",
    )
    self.categorie = categorie

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    if self.categorie in view.selected_categories:
      view.selected_categories.remove(self.categorie)
      self.style = discord.ButtonStyle.secondary
    else:
      view.selected_categories.add(self.categorie)
      self.style = discord.ButtonStyle.success
    await interaction.response.edit_message(view=view)


class DayButton(discord.ui.Button):

  def __init__(self, jour: str):
    super().__init__(
        label=jour, style=discord.ButtonStyle.secondary, custom_id=f"day_{jour}"
    )
    self.jour = jour

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    if self.jour in view.selected_jours:
      view.selected_jours.remove(self.jour)
      self.style = discord.ButtonStyle.secondary
    else:
      view.selected_jours.add(self.jour)
      self.style = discord.ButtonStyle.success
    await interaction.response.edit_message(view=view)


class CreneauButton(discord.ui.Button):

  def __init__(self, creneau: str):
    super().__init__(
        label=creneau,
        style=discord.ButtonStyle.secondary,
        custom_id=f"creneau_{creneau}",
    )
    self.creneau = creneau

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    if self.creneau in view.selected_creneaux:
      view.selected_creneaux.remove(self.creneau)
      self.style = discord.ButtonStyle.secondary
    else:
      view.selected_creneaux.add(self.creneau)
      self.style = discord.ButtonStyle.success
    await interaction.response.edit_message(view=view)


class ConfirmButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="Valider mes choix ✅",
        style=discord.ButtonStyle.primary,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    if (
        not view.selected_categories
        or not view.selected_jours
        or not view.selected_creneaux
    ):
      await interaction.response.send_message(
          "⚠️ Sélectionne au moins **une catégorie**, **un jour** et **un"
          " créneau** !",
          ephemeral=True,
      )
      return

    dispos = load_json(DISPOS_FILE, [])

    for cat in view.selected_categories:
      for jour in view.selected_jours:
        for creneau in view.selected_creneaux:
          dispos = [
              d
              for d in dispos
              if not (
                  d.get("course", "").lower() == view.course.lower()
                  and d["driver"].lower() == view.pilote.lower()
                  and d.get("categorie", "").lower() == cat.lower()
                  and d["jour"].lower() == jour.lower()
                  and d["creneau"].lower() == creneau.lower()
              )
          ]
          dispos.append({
              "course": view.course,
              "driver": view.pilote,
              "categorie": cat.upper(),
              "jour": jour,
              "creneau": creneau,
              "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
          })

    dispos = trier_dispos(dispos)
    save_json(DISPOS_FILE, dispos)

    cats_str = ", ".join(view.selected_categories)
    jours_str = ", ".join(view.selected_jours)
    creneaux_str = ", ".join(view.selected_creneaux)

    await interaction.response.edit_message(
        content=(
            f"✅ **Disponibilités enregistrées pour {view.course} !**\nPilote :"
            f" **{view.pilote}**\nCatégories : **{cats_str}**\nJours :"
            f" **{jours_str}**\nCréneaux : **{creneaux_str}**"
        ),
        view=None,
    )

    try:
      embed = generate_planning_embed(view.course)
      await interaction.followup.send(
          content=(
              f"📢 **Mise à jour du planning ({view.course}) par"
              f" {view.pilote} :**"
          ),
          embed=embed,
          ephemeral=False,
      )
    except Exception as e:
      print(f"Erreur d'envoi public : {e}")


class ResetButton(discord.ui.Button):

  def __init__(self):
    super().__init__(
        label="🗑️ Effacer mes dispos",
        style=discord.ButtonStyle.danger,
        row=4,
    )

  async def callback(self, interaction: discord.Interaction):
    view: DispoView = self.view
    dispos = load_json(DISPOS_FILE, [])

    nouvelles_dispos = [
        d
        for d in dispos
        if not (
            d.get("course", "").lower() == view.course.lower()
            and d["driver"].lower() == view.pilote.lower()
        )
    ]

    save_json(DISPOS_FILE, nouvelles_dispos)

    await interaction.response.edit_message(
        content=(
            f"🗑️ **Toutes tes disponibilités pour {view.course} ont été"
            f" supprimées, {view.pilote} !**"
        ),
        view=None,
    )

    try:
      embed = generate_planning_embed(view.course)
      await interaction.followup.send(
          content=(
              f"📢 **Mise à jour du planning ({view.course}) - Suppression par"
              f" {view.pilote} :**"
          ),
          embed=embed,
          ephemeral=False,
      )
    except Exception as e:
      print(f"Erreur d'envoi public : {e}")


# --- COMMANDE /dispo ---
@bot.tree.command(
    name="dispo",
    description="Indique tes disponibilités pour la course de ton choix",
)
@app_commands.describe(
    pilote="Sélectionne ton nom", course="Sélectionne la course"
)
async def dispo(interaction: discord.Interaction, pilote: str, course: str):
  config = load_json(CONFIG_FILE, {})
  course_data = config.get(course)

  if not course_data:
    await interaction.response.send_message(
        "⚠️ Cette course n'existe pas dans la configuration.", ephemeral=True
    )
    return

  categories = course_data.get("categories", ["HYPERCAR", "LMP2", "LMGT3"])
  jours = course_data.get("jours", ["Vendredi", "Samedi", "Dimanche"])
  creneaux = course_data.get(
      "creneaux", ["2h00", "7h00", "12h00", "17h00", "22h00"]
  )

  view = DispoView(pilote, course, categories, jours, creneaux)
  await interaction.response.send_message(
      f"🏁 **Panneau de disponibilités pour {pilote} — Course : {course}**\nCoche"
      " tes choix et valide :",
      view=view,
      ephemeral=True,
  )


# --- AUTO-COMPLÉTION ---
@dispo.autocomplete("pilote")
async def dispo_pilote_autocomplete(
    interaction: discord.Interaction, current: str
):
  drivers = load_json(DRIVERS_FILE, ["nic", "max", "yoan", "Aurelien"])
  return [
      app_commands.Choice(name=d, value=d)
      for d in drivers
      if current.lower() in d.lower()
  ]


@dispo.autocomplete("course")
async def dispo_course_autocomplete(
    interaction: discord.Interaction, current: str
):
  config = load_json(CONFIG_FILE, {})
  return [
      app_commands.Choice(name=c, value=c)
      for c, data in config.items()
      if current.lower() in c.lower()
      and data.get("statut", "actif") == "actif"
  ]


# --- COMMANDE /planning ---
@bot.tree.command(
    name="planning", description="Affiche le planning d'une course"
)
@app_commands.describe(course="Nom de la course à afficher")
async def planning(interaction: discord.Interaction, course: str):
  embed = generate_planning_embed(course)
  await interaction.response.send_message(embed=embed, ephemeral=False)


@planning.autocomplete("course")
async def planning_course_autocomplete(
    interaction: discord.Interaction, current: str
):
  config = load_json(CONFIG_FILE, {})
  return [
      app_commands.Choice(name=c, value=c)
      for c, data in config.items()
      if current.lower() in c.lower()
      and data.get("statut", "actif") == "actif"
  ]


# Lancement sécurisé du bot via variable d'environnement
bot.run(os.getenv("DISCORD_TOKEN"))