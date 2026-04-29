"""
Tony Q&A Discord Bot
--------------------
Students say "I have a question" → speak → say "Thank you"
Teacher answers anytime with !answer <id> <text>
"""

import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands, tasks

from config import Config
from qa_store import QAStore
from transcriber import Transcriber

# ── Bootstrap ──────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
qa = QAStore(Config.DB_PATH)
transcriber = Transcriber()

# Single worker — Whisper is CPU-bound; one job at a time avoids overloading Pi
_executor = ThreadPoolExecutor(max_workers=1)

# Minimum PCM bytes before we bother sending to Whisper (0.5 s at 48 kHz stereo int16)
_MIN_PCM_BYTES = 48000 * 2 * 2 // 2


# ── Per-user session state ─────────────────────────────────────────────────────
def _blank_session():
    return {
        "state": "idle",       # "idle" | "recording"
        "buffer": bytearray(),
        "transcript": "",
        "display_name": "Student",
    }

sessions: dict[int, dict] = defaultdict(_blank_session)

# ── Active voice state ─────────────────────────────────────────────────────────
active_vc: discord.VoiceClient | None = None
active_sink = None


# ── Custom PCM sink ────────────────────────────────────────────────────────────
class TonySink(discord.sinks.Sink):
    """Streams raw PCM from Discord into per-user buffers; processed by the loop."""

    def write(self, data: bytes, user) -> None:
        uid = user.id if hasattr(user, "id") else int(user)
        sessions[uid]["buffer"] += data

    def cleanup(self) -> None:
        pass


# ── Transcription loop (fires every CHUNK_SECONDS) ────────────────────────────
@tasks.loop(seconds=Config.CHUNK_SECONDS)
async def transcription_loop():
    if active_sink is None:
        return

    loop = asyncio.get_event_loop()

    for uid, sess in list(sessions.items()):
        if len(sess["buffer"]) < _MIN_PCM_BYTES:
            continue

        pcm = bytes(sess["buffer"])
        sess["buffer"] = bytearray()

        try:
            text = await loop.run_in_executor(_executor, transcriber.transcribe, pcm)
        except Exception as exc:
            print(f"[Whisper] Error (user {uid}): {exc}")
            continue

        if not text:
            continue

        print(f"[{sess['display_name']}] {text}")
        await _process_transcript(uid, sess, text.lower())


async def _process_transcript(uid: int, sess: dict, text: str):
    ch = bot.get_channel(Config.QUESTIONS_CHANNEL_ID)

    if sess["state"] == "idle":
        if Config.START_PHRASE in text:
            sess["state"] = "recording"
            sess["transcript"] = ""
            if ch:
                await ch.send(f"🎙️ **{sess['display_name']}** is asking a question…")

    elif sess["state"] == "recording":
        # Strip the start trigger in case it appears again mid-recording
        clean = text.replace(Config.START_PHRASE, "").strip()

        if Config.STOP_PHRASE in clean:
            # Everything before "thank you" is the question
            question_part = clean.split(Config.STOP_PHRASE)[0].strip(" .,!?")
            sess["transcript"] += " " + question_part
            question_text = sess["transcript"].strip()
            sess["state"] = "idle"
            sess["transcript"] = ""

            if question_text and ch:
                qid = qa.add_question(sess["display_name"], uid, question_text)
                await ch.send(
                    f"❓ **Question #{qid}** from **{sess['display_name']}**:\n"
                    f"> {question_text}\n"
                    f"*(Teacher: use `!answer {qid} your answer` to respond)*"
                )
        else:
            # Still accumulating the question
            sess["transcript"] += " " + clean.strip(" .,!?")


# ── Voice helpers ──────────────────────────────────────────────────────────────
async def join_voice(channel: discord.VoiceChannel):
    global active_vc, active_sink
    if active_vc and active_vc.is_connected():
        return

    active_vc = await channel.connect()
    active_sink = TonySink()
    active_vc.start_recording(active_sink, _on_recording_done)

    if not transcription_loop.is_running():
        transcription_loop.start()

    print(f"[Tony] Joined '{channel.name}' — listening for questions.")


async def leave_voice():
    global active_vc, active_sink
    if active_vc and active_vc.is_connected():
        if active_vc.is_recording():
            active_vc.stop_recording()
        await active_vc.disconnect()

    if transcription_loop.is_running():
        transcription_loop.stop()

    active_vc = None
    active_sink = None
    sessions.clear()
    print("[Tony] Left voice channel.")


async def _on_recording_done(sink, *args):
    """Called when stop_recording() fires — nothing to process here."""
    pass


# ── Auto-join / auto-leave via voice state events ─────────────────────────────
@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return

    target = Config.VOICE_CHANNEL_ID
    if not target:
        return

    if after.channel and after.channel.id == target:
        sessions[member.id]["display_name"] = member.display_name
        await join_voice(after.channel)

    elif before.channel and before.channel.id == target:
        non_bots = [m for m in before.channel.members if not m.bot]
        if not non_bots:
            await leave_voice()


@bot.event
async def on_ready():
    print(f"[Tony] Online as {bot.user} (ID: {bot.user.id})")
    print(f"[Tony] Questions channel: {Config.QUESTIONS_CHANNEL_ID}")
    print(f"[Tony] Auto-join VC: {Config.VOICE_CHANNEL_ID or 'disabled — use !join'}")


# ── Teacher / admin commands ───────────────────────────────────────────────────
@bot.command(name="join")
@commands.has_permissions(manage_channels=True)
async def cmd_join(ctx: commands.Context):
    """Join your current voice channel and start listening."""
    if not (ctx.author.voice and ctx.author.voice.channel):
        return await ctx.send("❌ You must be in a voice channel.")
    await join_voice(ctx.author.voice.channel)
    await ctx.send(f"✅ Joined **{ctx.author.voice.channel.name}** — listening for questions.")


@bot.command(name="leave")
@commands.has_permissions(manage_channels=True)
async def cmd_leave(ctx: commands.Context):
    """Leave voice channel and stop listening."""
    await leave_voice()
    await ctx.send("✅ Left voice channel.")


@bot.command(name="questions", aliases=["q", "pending"])
async def cmd_questions(ctx: commands.Context):
    """List all unanswered questions."""
    pending = qa.get_pending()
    if not pending:
        return await ctx.send("✅ No pending questions right now.")
    lines = [f"**{len(pending)} pending question(s):**"]
    for q in pending:
        lines.append(f"**#{q.id}** `{q.timestamp}` — **{q.student_name}**: {q.question_text}")
    await ctx.send("\n".join(lines))


@bot.command(name="answer", aliases=["a"])
async def cmd_answer(ctx: commands.Context, question_id: int, *, answer: str):
    """Answer a question: !answer <id> <your answer>"""
    q = qa.get_question(question_id)
    if not q:
        return await ctx.send(f"❌ Question #{question_id} not found.")
    if q.answer_text:
        return await ctx.send(f"❌ Question #{question_id} is already answered.")

    qa.answer_question(question_id, answer, ctx.author.display_name)

    ch = bot.get_channel(Config.QUESTIONS_CHANNEL_ID)
    if ch:
        await ch.send(
            f"✅ **Answer to #{question_id}** (asked by **{q.student_name}**):\n"
            f"> **Q:** {q.question_text}\n"
            f"> **A:** {answer}\n"
            f"*— {ctx.author.display_name}*"
        )
    await ctx.send(f"✅ Answered question #{question_id}.")


@bot.command(name="history")
async def cmd_history(ctx: commands.Context):
    """Show the last 10 questions (answered and pending)."""
    all_q = qa.get_all(limit=10)
    if not all_q:
        return await ctx.send("No questions recorded yet.")
    lines = ["**Recent Questions:**"]
    for q in all_q:
        icon = "✅" if q.answer_text else "⏳"
        lines.append(f"{icon} **#{q.id}** **{q.student_name}**: {q.question_text}")
        if q.answer_text:
            lines.append(f"   ↳ *{q.teacher_name}*: {q.answer_text}")
    await ctx.send("\n".join(lines))


@bot.command(name="thelp")
async def cmd_thelp(ctx: commands.Context):
    """Show Tony Q&A bot commands."""
    await ctx.send(
        "**Tony Q&A Bot**\n"
        "\n"
        "**Student flow:**\n"
        '1. Say **"I have a question"** → bot starts recording\n'
        "2. Ask your question naturally\n"
        '3. Say **"Thank you"** → question is saved and posted\n'
        "\n"
        "**Commands:**\n"
        "`!join` — Bot joins your voice channel *(admin/teacher)*\n"
        "`!leave` — Bot leaves voice channel *(admin/teacher)*\n"
        "`!questions` / `!q` — List pending questions\n"
        "`!answer <id> <text>` — Answer a question\n"
        "`!history` — Show last 10 Q&A entries\n"
    )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set. Export it as an environment variable.")
    if not Config.QUESTIONS_CHANNEL_ID:
        raise RuntimeError("QUESTIONS_CHANNEL_ID is not set.")
    bot.run(Config.DISCORD_TOKEN)
