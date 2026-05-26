NIJEL (Northern Ireland Jury Electronic Lookup)

Checks the Justice NI Juryline page and optionally posts the result to a Discord
channel.

## Configuration

Create a `.env` file in the project root. Use `.env.example` as a starting
point.

```env
NIJEL_JUROR_NUMBER=5000
NIJEL_COURT=Belfast
```

Optional Juryline settings:

```env
NIJEL_URL=https://www.justice-ni.gov.uk/articles/juryline-information
```

Optional Discord settings:

```env
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_CHANNEL_ID=your-channel-id
```

If both Discord variables are set, the script posts the Juryline result to that
channel with a single Discord API request. If they are not set, it prints the
result locally only.

Optional scheduler settings:

```env
NIJEL_SCHEDULE=daily
RUN_ON_START=true
NIJEL_RUN_TIME=19:00
NIJEL_TIMEZONE=Europe/Belfast
```

`NIJEL_SCHEDULE=once` runs once and exits. `NIJEL_SCHEDULE=daily` keeps the
container running and checks once per day. `Europe/Belfast` handles GMT/BST
automatically.

## Run

```bash
source venv/bin/activate
python main.py
```

## Docker

Build locally:

```bash
docker build -t nijel .
```

Run once locally:

```bash
docker run --rm --env-file .env nijel
```

Run as a long-running scheduled container:

```bash
docker compose up -d
```

The GitHub Actions workflow builds and pushes `ghcr.io/jdplays/nijel:latest`
on pushes to `main` and on manual dispatch.
