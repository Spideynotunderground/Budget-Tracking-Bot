"""Telegram budget bot: speak an expense, it gets logged."""

import csv
import io
import logging
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from config import ALLOWED_USER_IDS, CATEGORY_EMOJI, TELEGRAM_TOKEN
from parse import parse_expenses
from transcribe import transcribe

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

HELP = """🎙️ *Voice Budget Bot*

Just send me a voice message when you spend something:
_"Spent 15 on lunch"_ · _"Потратил 500 на продукты"_ · _"Gasté 20 en taxi"_

You can log several at once — _"12 on coffee and 40 on gas"_ — and typing works too.

*Commands*
/stats — this month's spending
/today — today's total
/list — recent expenses
/undo — remove the last one
/budget 1000 — set a monthly budget
/currency EUR — set your default currency
/export — download everything as CSV
"""


def money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def progress_bar(fraction: float, width: int = 10) -> str:
    filled = max(0, min(width, round(fraction * width)))
    return "█" * filled + "░" * (width - filled)


def authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return bool(update.effective_user and update.effective_user.id in ALLOWED_USER_IDS)


async def guard(update: Update) -> bool:
    """Reject unlisted users when an allowlist is configured."""
    if authorized(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("🔒 This is a private bot.")
    return False


# --------------------------------------------------------------------------- commands


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = update.effective_user
    await db.ensure_user(user.id, user.username)
    await update.message.reply_markdown(HELP)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)

    if not context.args:
        if user["monthly_budget"] is None:
            await update.message.reply_text("No budget set. Try /budget 1000")
        else:
            await update.message.reply_text(
                f"Monthly budget: {money(user['monthly_budget'], user['currency'])}\n"
                "Send /budget 0 to clear it."
            )
        return

    try:
        amount = Decimal(context.args[0].replace(",", ""))
    except InvalidOperation:
        await update.message.reply_text("That doesn't look like a number. Try /budget 1000")
        return

    if amount <= 0:
        await db.set_budget(update.effective_user.id, None)
        await update.message.reply_text("Budget cleared.")
        return

    await db.set_budget(update.effective_user.id, amount)
    await update.message.reply_text(f"✅ Monthly budget set to {money(amount, user['currency'])}")


async def cmd_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)

    if not context.args:
        await update.message.reply_text(
            f"Default currency is {user['currency']}. Change it with /currency EUR"
        )
        return

    code = context.args[0].upper()
    if not code.isalpha() or len(code) != 3:
        await update.message.reply_text("Use a 3-letter code, e.g. /currency EUR")
        return

    await db.set_currency(update.effective_user.id, code)
    await update.message.reply_text(f"✅ Default currency set to {code}")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)
    uid, currency = user["telegram_id"], user["currency"]

    total = await db.month_total(uid)
    rows = await db.month_by_category(uid)

    if not rows:
        await update.message.reply_text("Nothing logged this month yet. Send me a voice note!")
        return

    lines = [f"📊 *This month:* {money(total, currency)}"]

    if user["monthly_budget"]:
        budget = user["monthly_budget"]
        frac = float(total / budget) if budget else 0.0
        left = budget - total
        lines.append(f"{progress_bar(frac)}  {frac:.0%} of {money(budget, currency)}")
        lines.append(
            f"💚 {money(left, currency)} left"
            if left >= 0
            else f"🔴 {money(-left, currency)} over budget"
        )

    lines.append("")
    for row in rows:
        emoji = CATEGORY_EMOJI.get(row["category"], "📦")
        share = f"{float(row['total'] / total):.0%}" if total else "0%"
        lines.append(
            f"{emoji} {row['category'].title()} — {money(row['total'], currency)} ({share})"
        )

    await update.message.reply_markdown("\n".join(lines))


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)
    total = await db.today_total(user["telegram_id"])
    await update.message.reply_text(f"📅 Today: {money(total, user['currency'])}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)
    rows = await db.recent(user["telegram_id"], limit=10)

    if not rows:
        await update.message.reply_text("Nothing logged yet.")
        return

    lines = ["🧾 *Recent expenses*", ""]
    for row in rows:
        emoji = CATEGORY_EMOJI.get(row["category"], "📦")
        when = row["spent_at"].astimezone(db.TZ).strftime("%d %b")
        lines.append(f"{when} {emoji} {money(row['amount'], row['currency'])} — {row['note']}")

    await update.message.reply_markdown("\n".join(lines))


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    row = await db.delete_last(update.effective_user.id)
    if row is None:
        await update.message.reply_text("Nothing to undo.")
        return
    await update.message.reply_text(
        f"🗑 Removed {money(row['amount'], row['currency'])} — {row['note']}"
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    rows = await db.all_expenses(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Nothing to export yet.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "amount", "currency", "category", "note", "transcript"])
    for row in rows:
        writer.writerow(
            [
                row["spent_at"].astimezone(db.TZ).strftime("%Y-%m-%d %H:%M"),
                row["amount"],
                row["currency"],
                row["category"],
                row["note"],
                row["raw_text"],
            ]
        )

    await update.message.reply_document(
        document=io.BytesIO(buf.getvalue().encode("utf-8")),
        filename="expenses.csv",
        caption=f"{len(rows)} expenses",
    )


# ----------------------------------------------------------------------------- expenses


async def log_expenses(update: Update, text: str, source: str) -> None:
    """Shared path for voice and typed input: parse, store, reply with a summary."""
    message = update.effective_message
    user = await db.ensure_user(update.effective_user.id, update.effective_user.username)
    uid, currency = user["telegram_id"], user["currency"]

    parsed = await parse_expenses(text, currency)
    if not parsed:
        await message.reply_text(
            f'🤔 I heard _"{text}"_ but couldn\'t find an expense in it.\n'
            "Try something like _“spent 15 on lunch”_.",
            parse_mode="Markdown",
        )
        return

    ids = []
    for item in parsed:
        expense_id = await db.add_expense(
            telegram_id=uid,
            amount=item.amount,
            currency=item.currency,
            category=item.category,
            note=item.note,
            raw_text=text,
            spent_on=item.spent_on,
            source=source,
        )
        ids.append(expense_id)

    lines = []
    for item in parsed:
        emoji = CATEGORY_EMOJI.get(item.category, "📦")
        lines.append(
            f"✅ {emoji} {money(item.amount, item.currency)} — {item.note} _({item.category})_"
        )

    total = await db.month_total(uid)
    if user["monthly_budget"]:
        budget = user["monthly_budget"]
        frac = float(total / budget) if budget else 0.0
        left = budget - total
        lines.append("")
        lines.append(f"{progress_bar(frac)} {money(total, currency)} / {money(budget, currency)}")
        lines.append(
            f"💚 {money(left, currency)} left this month"
            if left >= 0
            else f"🔴 {money(-left, currency)} over budget"
        )
    else:
        lines.append("")
        lines.append(f"This month: {money(total, currency)}")

    # One undo button per logged row, so a mis-parsed item can be dropped immediately.
    buttons = [
        InlineKeyboardButton(f"↩️ Undo {money(item.amount, item.currency)}", callback_data=f"del:{eid}")
        for item, eid in zip(parsed, ids)
    ]
    keyboard = InlineKeyboardMarkup([[b] for b in buttons])

    await message.reply_markdown("\n".join(lines), reply_markup=keyboard)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    message = update.effective_message
    await message.chat.send_action(ChatAction.TYPING)
    status = await message.reply_text("🎧 Listening…")

    try:
        voice = message.voice or message.audio
        tg_file = await context.bot.get_file(voice.file_id)
        audio = bytes(await tg_file.download_as_bytearray())
        text = await transcribe(audio)
    except Exception:
        log.exception("transcription failed")
        await status.edit_text("😵 Couldn't transcribe that. Mind trying again?")
        return

    if not text:
        await status.edit_text("🤷 I didn't catch anything in that message.")
        return

    await status.delete()
    await log_expenses(update, text, source="voice")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await log_expenses(update, update.effective_message.text, source="text")


async def on_undo_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":", 1)[1])
    row = await db.delete_expense(update.effective_user.id, expense_id)

    if row is None:
        await query.answer("Already removed.", show_alert=False)
        return

    await query.edit_message_text(
        f"🗑 Removed {money(row['amount'], row['currency'])} — {row['note']}"
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("💥 Something broke on my side. Try again?")


# --------------------------------------------------------------------------- lifecycle


async def post_init(app: Application) -> None:
    await db.connect()
    log.info("database ready")


async def post_shutdown(app: Application) -> None:
    await db.close()


def main() -> None:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("currency", cmd_currency))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CallbackQueryHandler(on_undo_button, pattern=r"^del:\d+$"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    log.info("bot starting")
    app.run_polling()


if __name__ == "__main__":
    main()
