"""Telegram-бот с расписанием группы 4117 (только стандартная библиотека Python)."""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path


API = "https://api.telegram.org/bot{}/{}"
SCHEDULE_PATH = Path(__file__).with_name("schedule.json")
ENV_PATH = Path(__file__).with_name(".env")
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAY_BUTTONS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]


def api_call(token, method, data=None):
    body = urllib.parse.urlencode(data or {}).encode()
    request = urllib.request.Request(API.format(token, method), data=body)
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Telegram includes the useful reason (for example, "message is not
        # modified") in the JSON body even when the HTTP status is 400.
        try:
            payload = json.loads(error.read().decode("utf-8"))
            description = payload.get("description", str(error))
            error_code = payload.get("error_code", error.code)
        except (UnicodeDecodeError, json.JSONDecodeError):
            description = error.reason or str(error)
            error_code = error.code
        raise RuntimeError(f"Telegram API {error_code}: {description}") from error
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram API error"))
    return payload["result"]


def load_dotenv():
    """Загружает простые KEY=VALUE записи из .env, не затирая системное окружение."""
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_schedule():
    with SCHEDULE_PATH.open(encoding="utf-8") as file:
        data = json.load(file)
    return data


def make_keyboard():
    keyboard = [[{"text": "Сегодня", "callback_data": "today"}]]
    keyboard.extend([[{"text": name, "callback_data": f"weekday:{index}"}]
                     for index, name in enumerate(WEEKDAY_BUTTONS)])
    return json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False)


def make_dates_keyboard(weekday):
    data = load_schedule()
    year = data["year"]
    dates = set()
    for lesson in data.get("lessons", []):
        if lesson["weekday"] == weekday:
            for day in lesson["dates"]:
                full_date = date.fromisoformat(f"{year}-{day[3:5]}-{day[:2]}")
                if full_date.weekday() == weekday:
                    dates.add(full_date)
    if not dates:
        return None
    buttons = []
    for day in sorted(dates):
        buttons.append({"text": day.strftime("%d.%m.%Y"), "callback_data": f"date:{day.isoformat()}"})
    rows = [buttons[index:index + 3] for index in range(0, len(buttons), 3)]
    rows.append([{"text": "⬅️ К дням недели", "callback_data": "menu"}])
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


def format_day(day, lessons):
    date_label = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    result = [f"📅 {date_label} — {WEEKDAYS[date.fromisoformat(day).weekday()]}"]
    if not lessons:
        result.append("Занятий нет.")
    else:
        for number, lesson in enumerate(sorted(lessons, key=lambda item: item.get("time", "")), 1):
            time_text = f"{lesson['time']} — " if lesson.get("time") else ""
            kind = f" ({lesson['type']})" if lesson.get("type") else ""
            result.append(f"{number}. {time_text}{lesson['subject']}{kind}")
            if lesson.get("room"):
                result.append(f"   Аудитория: {lesson['room']}")
            if lesson.get("building"):
                result.append(f"   Корпус: {lesson['building']}")
            if lesson.get("note"):
                result.append(f"   {lesson['note']}")
    return "\n".join(result)


def get_schedule_data():
    data = load_schedule()
    lessons = data.get("lessons", [])
    year = data["year"]
    by_date = {}
    for lesson in lessons:
        for day in lesson["dates"]:
            full_date = date.fromisoformat(f"{year}-{day[3:5]}-{day[:2]}")
            if full_date.weekday() != lesson["weekday"]:
                raise ValueError(f"Дата {day} не соответствует дню недели в JSON")
            by_date.setdefault(full_date.isoformat(), []).append(lesson)
    return by_date


def schedule_text(choice):
    by_date = get_schedule_data()
    if choice == "today":
        today = date.today().isoformat()
        return format_day(today, by_date[today]) if today in by_date else "На сегодня расписание пока не добавлено."
    if choice.startswith("date:"):
        selected = choice.split(":", 1)[1]
        return format_day(selected, by_date[selected]) if selected in by_date else "Для этой даты расписание не найдено."

    weekday = int(choice.split(":", 1)[1])
    return f"Выберите дату ({WEEKDAY_BUTTONS[weekday].lower()}):"


def send_message(token, chat_id, text, keyboard=None):
    params = {"chat_id": chat_id, "text": text}
    if keyboard:
        params["reply_markup"] = keyboard
    api_call(token, "sendMessage", params)


def edit_message(token, chat_id, message_id, text, keyboard=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if keyboard:
        params["reply_markup"] = keyboard
    api_call(token, "editMessageText", params)


def send_schedule(token, chat_id, text):
    # Ограничение Telegram на длину сообщения — 4096 символов.
    chunks = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > 3800 and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    for index, chunk in enumerate(chunks):
        send_message(token, chat_id, chunk, make_keyboard() if index == len(chunks) - 1 else None)


def main():
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Добавьте TELEGRAM_BOT_TOKEN в файл .env")
    offset = None
    print("Бот запущен. Ожидаю сообщения…")
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            updates = api_call(token, "getUpdates", params)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                callback = update.get("callback_query")
                if message and message.get("text", "").startswith("/start"):
                    send_message(token, message["chat"]["id"],
                                 "Расписание группы 4117. Выберите день:", make_keyboard())
                elif callback:
                    choice = callback["data"]
                    try:
                        if choice == "menu":
                            edit_message(token, callback["message"]["chat"]["id"], callback["message"]["message_id"],
                                         "Расписание группы 4117. Выберите день:", make_keyboard())
                        elif choice.startswith("weekday:"):
                            weekday = int(choice.split(":", 1)[1])
                            keyboard = make_dates_keyboard(weekday)
                            text = schedule_text(choice)
                            edit_message(token, callback["message"]["chat"]["id"], callback["message"]["message_id"],
                                         text if keyboard else f"Для дня «{WEEKDAY_BUTTONS[weekday].lower()}» дат нет.", keyboard)
                        elif choice == "today":
                            text = schedule_text(choice)
                            edit_message(token, callback["message"]["chat"]["id"], callback["message"]["message_id"],
                                         text, make_keyboard())
                        elif choice.startswith("date:"):
                            text = schedule_text(choice)
                            edit_message(token, callback["message"]["chat"]["id"], callback["message"]["message_id"],
                                         text, make_keyboard())
                        else:
                            text = "Неизвестный выбор."
                    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                        print(f"Ошибка расписания: {error}")
                        text = "Не удалось прочитать расписание. Проверьте файл schedule.json."
                    api_call(token, "answerCallbackQuery", {"callback_query_id": callback["id"]})
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            print(f"Ошибка Telegram API: {error}. Повтор через 3 секунды.")
            time.sleep(3)


if __name__ == "__main__":
    main()
