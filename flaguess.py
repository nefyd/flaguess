import random

import aiosqlite
import requests
from interactions import (
  Client,
  Embed,
  File,
  IntervalTrigger,
  OptionType,
  SlashCommandChoice,
  SlashContext,
  Task,
  listen,
  slash_command,
  slash_option,
)
from interactions.api.events import MessageCreate


class Flaguess(Client):
  def __init__(
    self, country_names: list[str], rest_countries_version: float, *args, **kwargs
  ):
    super().__init__(*args, **kwargs)
    self.country_names = country_names
    self.rest_countries_version = rest_countries_version
    self.db: aiosqlite.Connection = None
    self.guild_query_flag_tasks = {}

  def _create_query_flag(self, guild_id, minutes=1):
    @Task.create(IntervalTrigger(minutes=minutes))
    async def query_flag():
      random_country_name = random.choice(self.country_names)

      country_url = f"https://restcountries.com/v{self.rest_countries_version}/name/{random_country_name}"
      country = requests.get(country_url).json()
      country_flag = country[0]["flags"]["png"]

      country_name = country[0]["name"]["common"].lower()

      await self.db.execute(
        "UPDATE guilds SET chosen_country = ? WHERE guild_id = ?",
        (country_name, guild_id),
      )
      await self.db.commit()

      embed = Embed()
      embed.set_image(url=country_flag)

      async with self.db.execute(
        """
        SELECT query_interval_min, query_interval_max, channel_id
        FROM guilds
        WHERE guild_id = ?
        """,
        (guild_id,),
      ) as cursor:
        row = await cursor.fetchone()
        query_flag_interval_minutes_min = row[0]
        query_flag_interval_minutes_max = row[1]
        db_channel_id = row[2]

      channel = await self.fetch_channel(db_channel_id)
      await channel.send(embed=embed)

      random_interval = random.randint(
        query_flag_interval_minutes_min, query_flag_interval_minutes_max
      )
      query_flag.reschedule(IntervalTrigger(minutes=random_interval))

    self.guild_query_flag_tasks[guild_id] = query_flag
    query_flag.start()

  @listen()
  async def on_startup(self):
    self.db = await aiosqlite.connect("flaguess.db")

    await self.db.execute("""
      CREATE TABLE IF NOT EXISTS guilds (
        guild_id INTEGER PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        query_interval_min INTEGER NOT NULL DEFAULT 1,
        query_interval_max INTEGER NOT NULL DEFAULT 1440,
        chosen_country TEXT,
        CONSTRAINT valid_intervals CHECK (query_interval_min <= query_interval_max)
      )
    """)
    await self.db.commit()

    async with self.db.execute("SELECT guild_id FROM guilds") as cursor:
      rows = await cursor.fetchall()
      for row in rows:
        guild_id = row[0]
        self._create_query_flag(guild_id)

    print("🟢 Flaguess is now online.")

  @listen()
  async def on_message_create(self, event: MessageCreate):
    if event.message.author.id == self.user.id:
      return

    guild_id = event.message.guild.id
    if guild_id not in self.guild_query_flag_tasks:
      return

    async with self.db.execute(
      "SELECT chosen_country FROM guilds WHERE guild_id = ?", (guild_id,)
    ) as cursor:
      row = await cursor.fetchone()
      chosen_country = row[0]

    if not chosen_country:
      return

    message = event.message.content.lower()

    if message == chosen_country:
      await event.message.reply("this is the country. well done!")
      await event.message.add_reaction("🎉")
      await event.message.add_reaction("🙌")
      await event.message.add_reaction("🍾")

      await self.db.execute("UPDATE guilds SET chosen_country = NULL WHERE guild_id = ?", (guild_id,))
      await self.db.commit()

  @slash_command(name="set_channel", description="set where flag queries are sent")
  @slash_option(
    name="channel_id",
    description="the channel's id",
    opt_type=OptionType.STRING,
    required=True,
  )
  async def set_channel(self, ctx: SlashContext, channel_id: str):
    if not await self.fetch_channel(channel_id):
      return await ctx.send("i can't find that channel")

    await self.db.execute(
      """
      INSERT INTO guilds (guild_id, channel_id)
      VALUES (?, ?)
      ON CONFLICT(guild_id)
      DO UPDATE SET channel_id = excluded.channel_id
      """,
      (int(ctx.guild_id), int(channel_id)),
    )
    await self.db.commit()

    guild_query_flag_task = self.guild_query_flag_tasks.get(ctx.guild_id)
    if guild_query_flag_task:
      guild_query_flag_task.stop()

    self._create_query_flag(ctx.guild_id)

    await ctx.send(f"i'll start sending flag queries to `{ctx.channel_id}` from now on")

  @slash_command("time_left", description="time left until next flag query")
  async def time_left(self, ctx: SlashContext):
    guild_query_flag_task = self.guild_query_flag_tasks.get(ctx.guild_id)
    if not guild_query_flag_task:
      return await ctx.send("this server has no flag query channel set")

    minutes_remaining = guild_query_flag_task.delta_until_run.total_seconds() / 60
    await ctx.send(f"the next flag query is in {minutes_remaining:.2f} minutes")

  @slash_command("set_interval", description="change flag query intervals")
  @slash_option(
    "interval_type",
    "the lower or upper bound",
    opt_type=OptionType.STRING,
    required=True,
    choices=[
      SlashCommandChoice("min", value="min"),
      SlashCommandChoice("max", value="max"),
    ],
  )
  @slash_option(
    "interval_time",
    "in minutes",
    opt_type=OptionType.INTEGER,
    required=True,
    min_value=1,
  )
  async def flag_interval(
    self, ctx: SlashContext, interval_type: str, interval_time: int
  ):
    if ctx.guild_id not in self.guild_query_flag_tasks:
      return await ctx.send("this server has no flag query channel set")

    match interval_type:
      case "min":
        await self.db.execute(
          "UPDATE guilds SET query_interval_min = ? WHERE guild_id = ?",
          (interval_time, ctx.guild_id),
        )
        await ctx.send(f"minimum interval changed to `{interval_time} minute(s)`")

      case "max":
        await self.db.execute(
          "UPDATE guilds SET query_interval_max = ? WHERE guild_id = ?",
          (interval_time, ctx.guild_id),
        )
        await ctx.send(f"maximum interval changed to `{interval_time} minute(s)`")

    await self.db.commit()

  @slash_command(name="all", description="list all the countries available")
  async def all(self, ctx: SlashContext):
    await ctx.send(file=File("countries.json"))

  @slash_command(name="ping", description="get the bot's latency")
  async def ping(self, ctx: SlashContext):
    if self.latency == float("inf"):
      return await ctx.send("im still warming up! wait a few seconds.")
    await ctx.send(f"i have a latency of {int(self.latency * 100)}ms")
