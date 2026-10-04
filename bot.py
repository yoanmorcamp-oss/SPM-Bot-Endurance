from datetime import datetime
import json
import os
import discord
from discord import app_commands
from discord.ext import commands, tasks

# Configuration des identifiants (Remplace par tes vrais ID Discord)
SALON_ENTRAINEMENT_ID = 1525497448305393705  # ID de ton salon textuel
ROLE_PILOTE_SPM_ID = 1222995895000371290  # ID du rôle @Pilote SPM

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


@bot.event
async def on_ready():
  # Enregistrement dynamique de la tâche de fond au démarrage du bot
  if not "RappelChampionnat" in bot.cogs:
    await bot.add_cog(RappelChampionnat(bot))

  print(f"Bot connecté en tant que {bot.user} !")
  try:
    synced = await bot.tree.sync()
    print(f"Commandes slash synchronisées : {len(synced)}")
  except Exception as e:
    print(e)


# (Ici se trouvent tes autres commandes habituelles /dispo, /planning, etc.)
# ...


# Lancement sécurisé du bot via variable d'environnement (Render)
bot.run(os.getenv("DISCORD_TOKEN"))
