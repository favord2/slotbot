import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput
import os
import asyncio
from datetime import datetime, timedelta
import pytz
import threading
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

flask_thread = Thread(target=run_flask, daemon=True)
flask_thread.start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

events = {}

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Ежедневная чистка в 22:05 МСК
@tasks.loop(hours=24)
async def daily_cleanup():
    now = datetime.now(MOSCOW_TZ)
    next_run = now.replace(hour=22, minute=5, second=0, microsecond=0)  # ← 22:05
    if now.hour > 22 or (now.hour == 22 and now.minute >= 5):
        next_run += timedelta(days=1)
    await asyncio.sleep((next_run - now).total_seconds())

    CHANNEL_ID = 1478992357327110220  # ID канала
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    setup_msg_id = None
    async for msg in channel.history(limit=100):
        if msg.author == bot.user and "**🔥 Панель создания стрел 🔥**" in msg.content:
            setup_msg_id = msg.id
            break

    if setup_msg_id:
        async for msg in channel.history(limit=None):
            if msg.id != setup_msg_id:
                try:
                    await msg.delete()
                except:
                    pass

# Пинг за 5 минут
async def schedule_ping(channel, message, event):
    try:
        date_str = event['date']
        time_str = event['time']
        time_clean = time_str.split()[0] if ' ' in time_str else time_str
        dt_str = f"{date_str} {time_clean}"
        dt_naive = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        dt_msk = MOSCOW_TZ.localize(dt_naive)

        ping_time = dt_msk - timedelta(minutes=5)
        now = datetime.now(MOSCOW_TZ)

        if ping_time <= now:
            return

        await asyncio.sleep((ping_time - now).total_seconds())

        if message.id not in events:
            return

        mentions = " ".join(f"<@{uid}>" for uid in event["participants"]) or "@everyone"
        await channel.send(
            f"{mentions}\n**СТРЕЛА начинается через 5 минут! 🔥**\nФормат: {event['format']}",
            reference=message
        )
    except Exception as e:
        print(f"Пинг ошибка: {e}")

# Кнопка Слот
class SlotButton(Button):
    def __init__(self, mid: int):
        super().__init__(label="Слот", style=discord.ButtonStyle.green, custom_id=f"slot_{mid}")
        self.mid = mid

    async def callback(self, interaction: discord.Interaction):
        event = events.get(self.mid)
        if not event:
            await interaction.response.send_message("Стрела удалена", ephemeral=True)
            return

        uid = interaction.user.id
        if uid in event["participants"]:
            await interaction.response.send_message("Ты уже записан", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event["participants"].append(uid)
        await update_event_message(interaction.message)

        await interaction.followup.send("Записался!", ephemeral=True)


# Кнопка Отмена
class CancelButton(Button):
    def __init__(self, mid: int):
        super().__init__(label="Отмена", style=discord.ButtonStyle.red, custom_id=f"cancel_{mid}")
        self.mid = mid

    async def callback(self, interaction: discord.Interaction):
        event = events.get(self.mid)
        if not event:
            await interaction.response.send_message("Стрела удалена", ephemeral=True)
            return

        uid = interaction.user.id
        if uid not in event["participants"]:
            await interaction.response.send_message("Ты не записан", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event["participants"].remove(uid)
        await update_event_message(interaction.message)

        await interaction.followup.send("Отписался", ephemeral=True)


# Обновление сообщения
async def update_event_message(message: discord.Message):
    event = events.get(message.id)
    if not event:
        return

    parts = [f"<@{uid}>" for uid in event["participants"]]
    list_text = "\n".join(parts) or "Пока пусто"

    content = (
        f"**🔥 СТРЕЛА 🔥** @everyone\n"
        f"**{event['date']} | {event['time']} | {event['server_number']} сервер**\n"
        f"**Формат: {event['format']}**   |   **Записались: {len(event['participants'])} чел.**\n"
        f"────────────────────────────\n"
        f"{list_text}\n"
        f"────────────────────────────"
    )

    await message.edit(content=content)


# Модалка создания стрелы
class CreateArrowModal(Modal, title="Создать новую стрелу"):
    server_number = TextInput(label="Номер сервера", placeholder="Номер сервера", required=True, max_length=50)
    time = TextInput(label="Время", placeholder="19:00 МСК", required=True, max_length=30)
    format_field = TextInput(label="Формат / кол-во", placeholder="3×3 / deagle shot rifle", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        sn = self.server_number.value.strip()
        t = self.time.value.strip()
        f = self.format_field.value.strip()

        # Дата берётся текущая (сегодня)
        today = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y")

        content = (
            f"**🔥 СТРЕЛА 🔥** @everyone\n"
            f"**{today} | {t} | {sn} сервер**\n"
            f"**Формат: {f}**   |   **Записались: 0 чел.**\n"
            f"────────────────────────────\n"
            f"Пока пусто\n"
            f"────────────────────────────"
        )

        view = View(timeout=None)
        msg = await interaction.channel.send(content, view=view)

        events[msg.id] = {
            "server_number": sn,
            "date": today,
            "time": t,
            "format": f,
            "participants": []
        }

        view.add_item(SlotButton(msg.id))
        view.add_item(CancelButton(msg.id))
        await msg.edit(view=view)

        asyncio.create_task(schedule_ping(interaction.channel, msg, events[msg.id]))

        await interaction.response.send_message("Стрела создана!", ephemeral=True)


# Панель создания
class CreateArrowButton(Button):
    def __init__(self):
        super().__init__(label="Создать стрелу", style=discord.ButtonStyle.blurple, custom_id="create_arrow", emoji="🔥")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateArrowModal())


class PersistentView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CreateArrowButton())


@bot.event
async def on_ready():
    print(f"Бот {bot.user} онлайн!")
    bot.add_view(PersistentView())
    if not daily_cleanup.is_running():
        daily_cleanup.start()


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    view = PersistentView()
    await ctx.send("**🔥 Панель создания стрел 🔥**\nНажми кнопку ниже, чтобы создать новую стрелу.", view=view)
    await ctx.message.delete()


bot.run(os.getenv("DISCORD_TOKEN"))

