import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from time import sleep
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

DEFAULT_URL = "https://www.justice-ni.gov.uk/articles/juryline-information"

load_dotenv()

@dataclass
class JuryRow:
    panel_text: str
    date_text: str
    detail_text: str


@dataclass
class JurylineConfig:
    juror_number: int
    court: str
    url: str
    html_file: str | None
    discord_bot_token: str | None
    discord_channel_id: int | None
    schedule: str
    run_on_start: bool
    run_time: str
    timezone: str


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def fetch_html(url: str) -> str:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.text

def load_html(url: str, html_file: str | None) -> str:
    if html_file:
        with open(html_file, "r", encoding="utf-8") as file:
            return file.read()

    return fetch_html(url)

def find_court_heading(soup: BeautifulSoup, court: str):
    court_lower = court.lower()

    for heading in soup.find_all(["h2", "h3"]):
        heading_text = normalise(heading.get_text(" "))
        if court_lower in heading_text.lower():
            return heading
    
    raise ValueError(f"Could not find court section matching: {court!r}")

def parse_rows_from_table(table) -> list[JuryRow]:
    rows: list[JuryRow] = []

    for tr in table.find_all("tr"):
        cells = [normalise(cell.get_text(" ")) for cell in tr.find_all(["td", "th"])]

        if len(cells) < 3:
            continue

        if "juror panel number" in cells[0].lower():
            continue

        rows.append(
            JuryRow(
                panel_text=cells[0],
                date_text=cells[1],
                detail_text=" ".join(cells[2:]),
            )
        )

    return rows

def get_court_rows(soup: BeautifulSoup, court: str) -> list[JuryRow]:
    heading = find_court_heading(soup, court)

    for element in heading.find_all_next():
        if element.name in {"h2", "h3"}:
            break

        if element.name == "table":
            rows = parse_rows_from_table(element)
            if rows:
                return rows

    raise ValueError(f"Could not find a jury table under court section: {court!r}")


def panel_matches(panel_text: str, juror_number: int) -> bool:
    text = panel_text.lower()

    range_match = re.search(r"\b(\d+)\s*(?:to|-|until)\s*(\d+)\b", text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return start <= juror_number <= end

    exact_numbers = [int(value) for value in re.findall(r"\b\d+\b", text)]
    if juror_number in exact_numbers:
        return True

    if "all jury panel numbers" in text or "all other jury panel numbers" in text:
        return True

    return False


def infer_attendance(detail_text: str) -> str:
    text = detail_text.lower()

    if re.search(r"\bnot required to attend\b", text):
        return "NOT_REQUIRED"

    if re.search(r"\bno longer required to attend\b", text):
        return "NOT_REQUIRED"

    if re.search(r"\brequired to attend\b", text):
        return "REQUIRED"

    if "please ring" in text or "phone the juryline" in text or "check the website" in text:
        return "CHECK_AGAIN"

    return "UNKNOWN"


def describe_status(status: str) -> str:
    if status == "REQUIRED":
        return "Your juror number appears to be required to attend."
    if status == "NOT_REQUIRED":
        return "Your juror number appears to be NOT required to attend."
    if status == "CHECK_AGAIN":
        return "Your juror number appears to need another Juryline / website check."
    return "Could not confidently determine attendance from the matched row."


def attendance_yes_no(status: str) -> str:
    if status == "REQUIRED":
        return "Yes"
    if status == "NOT_REQUIRED":
        return "No"
    return "Unknown"


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def get_config() -> JurylineConfig:
    juror_number_text = get_required_env("NIJEL_JUROR_NUMBER")
    discord_channel_id_text = os.environ.get("DISCORD_CHANNEL_ID")

    try:
        juror_number = int(juror_number_text)
    except ValueError as exc:
        raise ValueError("NIJEL_JUROR_NUMBER must be an integer") from exc

    try:
        discord_channel_id = (
            int(discord_channel_id_text) if discord_channel_id_text else None
        )
    except ValueError as exc:
        raise ValueError("DISCORD_CHANNEL_ID must be an integer") from exc

    return JurylineConfig(
        juror_number=juror_number,
        court=os.environ.get("NIJEL_COURT", "Belfast"),
        url=os.environ.get("NIJEL_URL", DEFAULT_URL),
        html_file=os.environ.get("NIJEL_HTML_FILE"),
        discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN"),
        discord_channel_id=discord_channel_id,
        schedule=os.environ.get("NIJEL_SCHEDULE", "once").strip().lower(),
        run_on_start=parse_bool(os.environ.get("RUN_ON_START"), default=False),
        run_time=os.environ.get("NIJEL_RUN_TIME", "19:00"),
        timezone=os.environ.get("NIJEL_TIMEZONE", "Europe/Belfast"),
    )


def check_juryline(config: JurylineConfig) -> tuple[str, int]:
    html = load_html(config.url, config.html_file)
    soup = BeautifulSoup(html, "html.parser")
    rows = get_court_rows(soup, config.court)

    matched_rows = [
        row for row in rows if panel_matches(row.panel_text, config.juror_number)
    ]

    if not matched_rows:
        return (
            "\n".join(
                [
                    "unknown",
                    "",
                    "No matching Juryline row found.",
                    "",
                    f"Court: {config.court}",
                    f"Juror number: {config.juror_number}",
                ]
            ),
            2,
        )

    messages: list[str] = []

    for row in matched_rows:
        status = infer_attendance(row.detail_text)
        answer = attendance_yes_no(status)
        messages.append(
            "\n".join(
                [
                    "## Juryline Check",
                    "",
                    f"**Attend:** {answer}",
                    f"**Date:** {row.date_text}",
                    f"**Court:** {config.court}",
                    f"**Juror number:** {config.juror_number}",
                    f"**Matched panel:** {row.panel_text}",
                    "",
                    "**Instruction**",
                    row.detail_text,
                ]
            )
        )

    return "\n\n---\n\n".join(messages), 0


def send_discord_message(
    token: str,
    channel_id: int,
    message: str,
    source_url: str,
) -> None:
    response = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        },
        json={
            "content": message,
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 5,
                            "label": "Open Juryline page",
                            "url": source_url,
                        }
                    ],
                }
            ],
        },
        timeout=20,
    )
    response.raise_for_status()


def parse_run_time(value: str) -> time:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise ValueError("NIJEL_RUN_TIME must use HH:MM format")

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError("NIJEL_RUN_TIME must be a valid 24-hour time")

    return time(hour=hour, minute=minute)


def seconds_until_next_run(run_time: time, timezone: str) -> float:
    zone = ZoneInfo(timezone)
    now = datetime.now(zone)
    next_run = datetime.combine(now.date(), run_time, tzinfo=zone)

    if next_run <= now:
        next_run += timedelta(days=1)

    return (next_run - now).total_seconds()


def run_once(config: JurylineConfig) -> int:
    message, status_code = check_juryline(config)

    print(message, flush=True)

    if config.discord_bot_token and config.discord_channel_id:
        send_discord_message(
            config.discord_bot_token,
            config.discord_channel_id,
            message,
            config.url,
        )
    elif config.discord_bot_token or config.discord_channel_id:
        raise ValueError(
            "Set both DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID to send to Discord"
        )

    return status_code


def run_once_safely(config: JurylineConfig) -> int:
    try:
        return run_once(config)
    except requests.RequestException as exc:
        print(f"Network/API request failed: {exc}", file=sys.stderr, flush=True)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


def run_daily(config: JurylineConfig) -> int:
    run_time = parse_run_time(config.run_time)

    if config.run_on_start:
        run_once_safely(config)

    while True:
        wait_seconds = seconds_until_next_run(run_time, config.timezone)
        next_run = datetime.now(ZoneInfo(config.timezone)) + timedelta(
            seconds=wait_seconds
        )
        print(
            f"Next Juryline check scheduled for {next_run.isoformat(timespec='minutes')}",
            flush=True,
        )
        sleep(wait_seconds)
        run_once_safely(config)


def main() -> int:
    try:
        config = get_config()

        if config.schedule == "daily":
            return run_daily(config)
        if config.schedule == "once":
            return run_once_safely(config)

        raise ValueError("NIJEL_SCHEDULE must be 'once' or 'daily'")

    except ValueError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
