# 🎙️ Voice Budget Bot

Log expenses by sending a Telegram voice message. Speech goes in, structured
data comes out.

```
🎤 You: (voice) "Spent 15 on lunch and 30 on gas"

🤖 Bot: ✅ 🍔 15.00 USD — lunch (food)
        ✅ 🚕 30.00 USD — gas (transport)

        ████░░░░░░ 420.00 USD / 1,000.00 USD
        💚 580.00 USD left this month
        [↩️ Undo 15.00 USD] [↩️ Undo 30.00 USD]
```

Speaks English, Russian and Spanish — the language is auto-detected, so you can
switch mid-week without changing a setting.

## How it works

| Step | What happens | Cost |
|---|---|---|
| Voice → text | Groq-hosted Whisper large-v3 | free tier |
| Text → structured expense | Groq-hosted Llama 3.3 70B, JSON mode | free tier |
| Storage | PostgreSQL | free (self-hosted) |

Both AI steps run on Groq's free tier, which is far more than a personal
expense tracker will use. Free-tier limits change over time — check
[console.groq.com](https://console.groq.com) for current numbers.

## Setup

**1. Get your two keys**

- Telegram token: message [@BotFather](https://t.me/BotFather) → `/newbot`
- Groq key: [console.groq.com/keys](https://console.groq.com/keys) (free, no card)

**2. Configure**

```bash
cp .env.example .env
# fill in TELEGRAM_TOKEN and GROQ_API_KEY
```

Set `ALLOWED_USER_IDS` to your own Telegram user ID (get it from
[@userinfobot](https://t.me/userinfobot)) so nobody else can log expenses into
your database. Leaving it empty lets anyone who finds the bot use it.

**3. Start Postgres**

```bash
docker compose up -d          # or: podman compose up -d
```

The schema is applied automatically on first run — no migration step.

**4. Install and run**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bot.py
```

Send your bot a voice message. That's it.

## Commands

| Command | Does |
|---|---|
| `/stats` | This month's total, budget progress, category breakdown |
| `/today` | Today's total |
| `/list` | 10 most recent expenses |
| `/undo` | Remove the last expense |
| `/budget 1000` | Set a monthly budget (`/budget 0` clears it) |
| `/currency EUR` | Set your default currency |
| `/export` | Download everything as CSV |

Typed messages work exactly like voice ones, which is handy when you're
somewhere you can't talk.

## Configuration

Everything lives in `.env`:

- `BOT_TIMEZONE` — decides where "today" and "this month" begin. Default `UTC`;
  set it to your own zone (e.g. `Asia/Karachi`) or daily totals will roll over
  at the wrong hour.
- `DEFAULT_CURRENCY` — assumed when you don't name a currency out loud.
- `GROQ_STT_MODEL` / `GROQ_LLM_MODEL` — swap in other Groq models.

## Known limitations

- **Mixed currencies are summed naively.** If you log both USD and EUR, `/stats`
  adds the numbers together without converting. Fine if you stick to one
  currency; needs an FX rate lookup otherwise.
- **No recurring expenses.** Every entry is a one-off.
- **The LLM occasionally miscategorises.** That's what the inline ↩️ Undo button
  is for — tap it and say it again.

## Deploying it 24/7

The bot must be running to receive messages. On your laptop it only works while
the laptop is awake. For always-on, any small host works — Railway, Fly.io and
Render all have cheap tiers and managed Postgres. Point `DATABASE_URL` at the
managed database and deploy; no code changes needed.

## Swapping in free offline transcription

`transcribe.py` has a single `transcribe(audio: bytes) -> str` function and
nothing else imports the backend. To run fully offline, `pip install
faster-whisper` and reimplement that one function — the rest of the bot is
unchanged.

## Project layout

```
bot.py           Telegram handlers, commands, reply formatting
transcribe.py    voice → text (Groq Whisper)
parse.py         text → structured expenses (Groq Llama, JSON mode)
db.py            Postgres access layer
config.py        env config, categories, emoji
schema.sql       tables, applied automatically at startup
```
