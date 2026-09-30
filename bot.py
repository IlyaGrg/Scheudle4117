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
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
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


def schedule_text(choice):
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
    if choice == "today":
        today = date.today().isoformat()
        return format_day(today, by_date[today]) if today in by_date else "На сегодня расписание пока не добавлено."

    weekday = int(choice.split(":", 1)[1])
    matching = sorted(day for day in by_date if date.fromisoformat(day).weekday() == weekday)
    if not matching:
        return f"В JSON пока нет дат для дня «{WEEKDAY_BUTTONS[weekday].lower()}»."
    return "\n\n".join(format_day(day, by_date[day]) for day in matching)


def send_message(token, chat_id, text, keyboard=None):
    params = {"chat_id": chat_id, "text": text}
    if keyboard:
        params["reply_markup"] = keyboard
    api_call(token, "sendMessage", params)


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
                        text = schedule_text(choice) if choice == "today" or choice.startswith("weekday:") else "Неизвестный выбор."
                    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                        print(f"Ошибка расписания: {error}")
                        text = "Не удалось прочитать расписание. Проверьте файл schedule.json."
                    api_call(token, "answerCallbackQuery", {"callback_query_id": callback["id"]})
                    send_schedule(token, callback["message"]["chat"]["id"], text)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            print(f"Ошибка Telegram API: {error}. Повтор через 3 секунды.")
            time.sleep(3)


if __name__ == "__main__":
    main()
