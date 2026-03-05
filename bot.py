import discord
from discord.ext import commands
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

# Flask для keep-alive на Render (free Web Service)
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot is alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

flask_thread = Thread(target=run_flask, daemon=True)
flask_thread.start()

# Настройки бота
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Хранилище стрелок (в памяти)
events = {}

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# ───────────────────────────────────────────────
# Планирование пинга за 1 минуту до начала
# ───────────────────────────────────────────────
async def schedule_ping(channel: discord.TextChannel, message: discord.Message, event: dict):
    try:
        date_str = event['date']          # "05.03.2026"
        time_str = event['time']          # "19:00" или "19:00 МСК"

        # Убираем "МСК" или лишнее после пробела
        time_clean = time_str.split()[0] if ' ' in time_str else time_str

        dt_str = f"{date_str} {time_clean}"
        dt_naive = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")

        # Делаем timezone-aware (МСК)
        dt_msk = MOSCOW_TZ.localize(dt_naive)

        # Время пинга: за 60 секунд до
        ping_time = dt_msk - timedelta(minutes=5)

        # Текущее время в МСК
        now_msk = datetime.now(MOSCOW_TZ)

        if ping_time <= now_msk:
            print(f"Время пинга для стрелы {message.id} уже прошло или наступило")
            return

        seconds_to_wait = (ping_time - now_msk).total_seconds()
        print(f"Пинг для стрелы {message.id} запланирован через {seconds_to_wait:.0f} сек")

        await asyncio.sleep(seconds_to_wait)

        # Проверяем, что стрела ещё существует
        if message.id not in events:
            print("Стрела удалена до пинга")
            return

        mentions = " ".join([f"<@{uid}>" for uid in event["participants"]]) or "@everyone"

        await channel.send(
            f"{mentions}\n**Стрела начинается через 5 минут!**\nФормат: {event['format']}",
            reference=message
        )
        print(f"Пинг отправлен для стрелы {message.id}")

    except Exception as e:
        print(f"Ошибка при пинге: {e}")


# ───────────────────────────────────────────────
# Кнопка "Слот" с defer
# ───────────────────────────────────────────────
class SlotButton(Button):
    def __init__(self, event_message_id: int):
        super().__init__(label="Слот", style=discord.ButtonStyle.green, custom_id=f"slot_{event_message_id}")
        self.event_message_id = event_message_id

    async def callback(self, interaction: discord.Interaction):
        event = events.get(self.event_message_id)
        if not event:
            await interaction.response.send_message("Стрела уже удалена или устарела.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id in event["participants"]:
            await interaction.response.send_message("Ты уже записан!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        event["participants"].append(user_id)
        await self.update_event_message(interaction.message)

        await interaction.followup.send("Записался успешно!", ephemeral=True)

    async def update_event_message(self, message: discord.Message):
        event = events.get(message.id)
        if not event: return

        participants = [f"<@{uid}>" for uid in event["participants"]]
        list_text = "\n".join(participants) or "Пока пусто"

        content = (
            f"**🔥 СТРЕЛА 🔥**\n"
            f"**{event['date']} | {event['time']} | {event['server_number']} сервер**\n"
            f"**Формат: {event['format']}**   |   **Записались: {len(event['participants'])} чел.**\n"
            f"────────────────────────────\n"
            f"{list_text}\n"
            f"────────────────────────────"
        )

        await message.edit(content=content)


# ───────────────────────────────────────────────
# Модалка создания стрелы
# ───────────────────────────────────────────────
class CreateArrowModal(Modal, title="Создать новую стрелу"):
    server_number = TextInput(
        label="Номер сервера",
        placeholder="Номер сервера",
        style=discord.TextStyle.short,
        required=True,
        max_length=50
    )
    date = TextInput(
        label="Дата (ДД.ММ.ГГГГ)",
        placeholder="05.03.2026",
        style=discord.TextStyle.short,
        required=True,
        max_length=10
    )
    time = TextInput(
        label="Время",
        placeholder="19:00 МСК",
        style=discord.TextStyle.short,
        required=True,
        max_length=30
    )
    format_field = TextInput(
        label="Формат / кол-во + оружие",
        placeholder="2×2 / 3×3 / 4×4 / 5x5 + оружие",
        style=discord.TextStyle.short,
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        server_number = self.server_number.value.strip()
        date_str = self.date.value.strip()
        time_str = self.time.value.strip()
        format_str = self.format_field.value.strip()

        content = (
            f"**🔥 СТРЕЛА 🔥**\n"
            f"**{date_str} | {time_str} | {server_number} сервер**\n"
            f"**Формат: {format_str}**   |   **Записались: 0 чел.**\n"
            f"────────────────────────────\n"
            f"Пока пусто\n"
            f"────────────────────────────"
        )

        view = View(timeout=None)
        msg = await interaction.channel.send(content, view=view)

        events[msg.id] = {
            "server_number": server_number,
            "date": date_str,
            "time": time_str,
            "format": format_str,
            "participants": []
        }

        view.add_item(SlotButton(msg.id))
        await msg.edit(view=view)

        # Планируем пинг
        asyncio.create_task(
            schedule_ping(interaction.channel, msg, events[msg.id])
        )

        await interaction.response.send_message("Стрела создана! 🔥 Пинг за 1 минуту до начала.", ephemeral=True)


# ───────────────────────────────────────────────
# Кнопка "Создать стрелу"
# ───────────────────────────────────────────────
class CreateArrowButton(Button):
    def __init__(self):
        super().__init__(
            label="Создать стрелу",
            style=discord.ButtonStyle.blurple,
            custom_id="create_arrow",
            emoji="🔥"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateArrowModal())


class PersistentView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CreateArrowButton())


# ───────────────────────────────────────────────
# События
# ───────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Бот {bot.user} онлайн!")
    bot.add_view(PersistentView())


@bot.command()
@commands.has_permissions(administrator=True)
async def setup(ctx):
    view = PersistentView()
    await ctx.send(
        "**🔥 Панель создания стрел 🔥**\n"
        "Нажми кнопку ниже, чтобы создать новую стрелу.",
        view=view
    )
    await ctx.message.delete()


# Запуск
bot.run(os.getenv("DISCORD_TOKEN"))