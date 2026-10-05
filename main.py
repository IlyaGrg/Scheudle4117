"""Telegram-бот расписания группы 4117 на aiogram 3."""

import asyncio
import json
import os
from datetime import date, datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_PATH = BASE_DIR / "schedule.json"
ENV_PATH = BASE_DIR / ".env"
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAY_BUTTONS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def load_dotenv():
    """Загружает простые KEY=VALUE записи, не затирая системное окружение."""
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("\"'"))


def load_schedule():
    with SCHEDULE_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def make_main_keyboard():
    rows = [[InlineKeyboardButton(text="Сегодня", callback_data="today")]]
    rows.extend([[InlineKeyboardButton(text=name, callback_data=f"weekday:{index}")]
                 for index, name in enumerate(WEEKDAY_BUTTONS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def make_dates_keyboard(weekday):
    data = load_schedule()
    dates = set()
    for lesson in data.get("lessons", []):
        if lesson.get("weekday") == weekday:
            for day in lesson.get("dates", []):
                full_date = date.fromisoformat(f"{data['year']}-{day[3:5]}-{day[:2]}")
                if full_date.weekday() == weekday:
                    dates.add(full_date)
    if not dates:
        return None
    buttons = [InlineKeyboardButton(text=day.strftime("%d.%m.%Y"),
                                    callback_data=f"date:{day.isoformat()}")
               for day in sorted(dates)]
    rows = [buttons[index:index + 3] for index in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="⬅️ К дням недели", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_by_date():
    data = load_schedule()
    by_date = {}
    for lesson in data.get("lessons", []):
        for day in lesson.get("dates", []):
            full_date = date.fromisoformat(f"{data['year']}-{day[3:5]}-{day[:2]}")
            if full_date.weekday() != lesson["weekday"]:
                raise ValueError(f"Дата {day} не соответствует дню недели в schedule.json")
            by_date.setdefault(full_date.isoformat(), []).append(lesson)
    return by_date


def format_day(day, lessons):
    date_label = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    lines = [f"📅 {date_label} — {WEEKDAYS[date.fromisoformat(day).weekday()]}"]
    if not lessons:
        lines.append("Занятий нет.")
    for number, lesson in enumerate(sorted(lessons, key=lambda item: item.get("time", "")), 1):
        time_text = f"{lesson['time']} — " if lesson.get("time") else ""
        kind = f" ({lesson['type']})" if lesson.get("type") else ""
        lines.append(f"{number}. {time_text}{lesson['subject']}{kind}")
        if lesson.get("room"):
            lines.append(f"   Аудитория: {lesson['room']}")
        if lesson.get("building"):
            lines.append(f"   Корпус: {lesson['building']}")
        if lesson.get("note"):
            lines.append(f"   {lesson['note']}")
    return "\n".join(lines)


def schedule_text(choice):
    by_date = schedule_by_date()
    if choice == "today":
        today = date.today().isoformat()
        return format_day(today, by_date[today]) if today in by_date else "На сегодня расписание пока не добавлено."
    if choice.startswith("date:"):
        selected = choice.split(":", 1)[1]
        return format_day(selected, by_date[selected]) if selected in by_date else "Для этой даты расписание не найдено."
    weekday = int(choice.split(":", 1)[1])
    if not 0 <= weekday < len(WEEKDAY_BUTTONS):
        raise ValueError("Некорректный день недели")
    return f"Выберите дату ({WEEKDAY_BUTTONS[weekday].lower()}):"


def split_message(text, limit=3800):
    """Разбивает расписание на сообщения короче лимита Telegram."""
    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def send_schedule(message: Message, text: str):
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=make_main_keyboard() if index == len(chunks) - 1 else None)


async def main():
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or token == "ВСТАВЬТЕ_ТОКЕН_СЮДА":
        raise SystemExit("Добавьте действительный TELEGRAM_BOT_TOKEN в файл .env")

    bot = Bot(token=token)
    dispatcher = Dispatcher()

    @dispatcher.message(CommandStart())
    async def start(message: Message):
        await message.answer("Расписание группы 4117. Выберите день:", reply_markup=make_main_keyboard())

    @dispatcher.callback_query(F.data)
    async def callback_handler(query: CallbackQuery):
        await query.answer()
        if not query.message:
            return
        choice = query.data or ""
        try:
            if choice == "menu":
                await query.message.edit_text("Расписание группы 4117. Выберите день:",
                                              reply_markup=make_main_keyboard())
            elif choice.startswith("weekday:"):
                weekday = int(choice.split(":", 1)[1])
                if not 0 <= weekday < len(WEEKDAY_BUTTONS):
                    raise ValueError("Некорректный день недели")
                keyboard = make_dates_keyboard(weekday)
                text = schedule_text(choice) if keyboard else f"Для дня «{WEEKDAY_BUTTONS[weekday].lower()}» дат нет."
                await query.message.edit_text(text, reply_markup=keyboard)
            elif choice == "today" or choice.startswith("date:"):
                await send_schedule(query.message, schedule_text(choice))
            else:
                await query.message.answer("Неизвестный выбор.")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as error:
            print(f"Ошибка расписания: {error}")
            await query.message.answer("Не удалось прочитать расписание. Проверьте файл schedule.json.")

    try:
        print("Бот запущен. Ожидаю сообщения…")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
