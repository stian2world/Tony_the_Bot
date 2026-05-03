"""
Tony Discord Bot
----------------
Voice flow  : "I have a question" → Whisper → Groq auto-answer → posted in tonys-chat-room
Text flow   : any message in tonys-chat-room → Groq reply (checks past Q&A first)
General     : Tony only replies when @mentioned
1-on-1 voice: auto-joins both "1 on 1 with Tony" channels when a student enters
"""

import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands, tasks

from config import Config
from figurate_client import fetch_tony_system_prompt
from groq_client import TonyGroq
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

# Load Tony's personality from Figurate, then pass it to Groq
print("[Tony] Fetching personality from Figurate…")
_system_prompt = fetch_tony_system_prompt(
    api_key=Config.FIGURATE_API_KEY,
    character_id=Config.FIGURATE_CHARACTER_ID,
)
tony = TonyGroq(api_key=Config.GROQ_API_KEY, model=Config.GROQ_MODEL, system_prompt=_system_prompt)

_executor = ThreadPoolExecutor(max_workers=1)
_MIN_PCM_BYTES = 48000 * 2 * 2 // 2

# Per-voice-channel state: channel_id → {vc, sink}
active_vcs: dict[int, dict] = {}

# Per-user voice session state
def _blank_session():
    return {"state": "idle", "buffer": bytearray(), "transcript": "", "display_name": "Student"}

sessions: dict[int, dict] = defaultdict(_blank_session)


# ── Groq helper ────────────────────────────────────────────────────────────────
async def _tony_reply(question: str) -> str:
    """Check past Q&A for a similar answer, then ask Groq."""
    loop = asyncio.get_event_loop()
    similar = await loop.run_in_executor(None, qa.find_similar, question)
    prior = similar.answer_text if similar else ""
    answer = await loop.run_in_executor(None, tony.ask, question, prior)
    return answer, bool(similar)


# ── Custom PCM sink ────────────────────────────────────────────────────────────
class TonySink(discord.sinks.Sink):
    def write(self, data: bytes, user) -> None:
        uid = user.id if hasattr(user, "id") else int(user)
        sessions[uid]["buffer"] += data

    def cleanup(self) -> None:
        pass


# ── Transcription loop ────────────────────────────────────────────────────────
@tasks.loop(seconds=Config.CHUNK_SECONDS)
async def transcription_loop():
    if not active_vcs:
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
        clean = text.replace(Config.START_PHRASE, "").strip()
        if Config.STOP_PHRASE in clean:
            question_part = clean.split(Config.STOP_PHRASE)[0].strip(" .,!?")
            sess["transcript"] += " " + question_part
            question_text = sess["transcript"].strip()
            sess["state"] = "idle"
            sess["transcript"] = ""

            if question_text and ch:
                qid = qa.add_question(sess["display_name"], uid, question_text)
                await ch.send(
                    f"❓ **Question #{qid}** from **{sess['display_name']}**:\n"
                    f"> {question_text}"
                )
                async with ch.typing():
                    answer, from_cache = await _tony_reply(question_text)
                qa.answer_question(qid, answer, "Tony (AI)")
                cache_note = " *(similar question answered before)*" if from_cache else ""
                await ch.send(f"💡 **Tony's answer**{cache_note}:\n{answer}")
        else:
            sess["transcript"] += " " + clean.strip(" .,!?")


# ── Voice helpers ──────────────────────────────────────────────────────────────
async def join_voice(channel: discord.VoiceChannel):
    cid = channel.id
    if cid in active_vcs and active_vcs[cid]["vc"].is_connected():
        return
    vc = await channel.connect()
    sink = TonySink()
    vc.start_recording(sink, _on_recording_done)
    active_vcs[cid] = {"vc": vc, "sink": sink}
    if not transcription_loop.is_running():
        transcription_loop.start()
    print(f"[Tony] Joined '{channel.name}'")


async def leave_voice(channel_id: int):
    state = active_vcs.pop(channel_id, None)
    if state:
        vc = state["vc"]
        if vc.is_recording():
            vc.stop_recording()
        if vc.is_connected():
            await vc.disconnect()
    if not active_vcs and transcription_loop.is_running():
        transcription_loop.stop()
    sessions.clear()
    print(f"[Tony] Left voice channel {channel_id}")


async def _on_recording_done(sink, *args):
    pass


# ── Auto-join / auto-leave ─────────────────────────────────────────────────────
@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    if member.bot:
        return

    if after.channel and after.channel.id in Config.VOICE_CHANNEL_IDS:
        sessions[member.id]["display_name"] = member.display_name
        await join_voice(after.channel)

    if before.channel and before.channel.id in Config.VOICE_CHANNEL_IDS:
        non_bots = [m for m in before.channel.members if not m.bot]
        if not non_bots:
            await leave_voice(before.channel.id)


# ── Text message handler ───────────────────────────────────────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    # tonys-chat-room: respond to every message
    if message.channel.id == Config.QUESTIONS_CHANNEL_ID:
        question = message.content.strip()
        if not question or question.startswith("!"):
            await bot.process_commands(message)
            return
        async with message.channel.typing():
            answer, from_cache = await _tony_reply(question)
        cache_note = " *(similar question answered before)*" if from_cache else ""
        await message.reply(f"💡 **Tony**{cache_note}:\n{answer}")

    # general channel: only reply when @mentioned
    elif message.channel.id == Config.GENERAL_CHANNEL_ID and bot.user in message.mentions:
        question = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if question:
            async with message.channel.typing():
                answer, _ = await _tony_reply(question)
            await message.reply(f"💡 **Tony**:\n{answer}")

    await bot.process_commands(message)


# ── Welcome DM on member join ──────────────────────────────────────────────────
@bot.event
async def on_member_join(member: discord.Member):
    try:
        await member.send(
            f"👋 Hey **{member.display_name}**, welcome! I'm **Tony**, your AI assistant.\n\n"
            f"You can ask me anything right here in this DM, or head to "
            f"**#tonys-chat-room** on the server to ask questions alongside your classmates.\n\n"
            f"For voice Q&A, join one of the **1 on 1 with Tony** voice channels and say "
            f"*\"I have a question\"* to start."
        )
    except discord.Forbidden:
        pass  # user has DMs disabled


@bot.event
async def on_ready():
    print(f"[Tony] Online as {bot.user} (ID: {bot.user.id})")
    print(f"[Tony] Q&A channel : {Config.QUESTIONS_CHANNEL_ID}")
    print(f"[Tony] General     : {Config.GENERAL_CHANNEL_ID}")
    print(f"[Tony] Voice slots : {Config.VOICE_CHANNEL_IDS}")
    print(f"[Tony] Groq model  : {Config.GROQ_MODEL}")


# ── Admin commands ─────────────────────────────────────────────────────────────
@bot.command(name="join")
@commands.has_permissions(manage_channels=True)
async def cmd_join(ctx: commands.Context):
    if not (ctx.author.voice and ctx.author.voice.channel):
        return await ctx.send("❌ You must be in a voice channel.")
    await join_voice(ctx.author.voice.channel)
    await ctx.send(f"✅ Joined **{ctx.author.voice.channel.name}**")


@bot.command(name="leave")
@commands.has_permissions(manage_channels=True)
async def cmd_leave(ctx: commands.Context):
    if not (ctx.author.voice and ctx.author.voice.channel):
        return await ctx.send("❌ You must be in a voice channel.")
    await leave_voice(ctx.author.voice.channel.id)
    await ctx.send("✅ Left voice channel.")


@bot.command(name="questions", aliases=["q", "pending"])
async def cmd_questions(ctx: commands.Context):
    pending = qa.get_pending()
    if not pending:
        return await ctx.send("✅ No pending questions right now.")
    lines = [f"**{len(pending)} pending question(s):**"]
    for q in pending:
        lines.append(f"**#{q.id}** `{q.timestamp}` — **{q.student_name}**: {q.question_text}")
    await ctx.send("\n".join(lines))


@bot.command(name="answer", aliases=["a"])
async def cmd_answer(ctx: commands.Context, question_id: int, *, answer: str):
    q = qa.get_question(question_id)
    if not q:
        return await ctx.send(f"❌ Question #{question_id} not found.")
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
    await ctx.send(
        "**Tony Bot**\n\n"
        "**Text chat:**\n"
        "• Type anything in **#tonys-chat-room** → Tony answers instantly\n"
        "• Mention **@Tony** in **#general** → Tony replies\n\n"
        "**Voice chat:**\n"
        "1. Join a **1 on 1 with Tony** voice channel\n"
        '2. Say **"I have a question"** → Tony starts listening\n'
        "3. Ask your question\n"
        '4. Say **"Thank you"** → answer is posted in **#tonys-chat-room**\n\n'
        "**Commands:**\n"
        "`!join` / `!leave` — manual voice control *(admin)*\n"
        "`!questions` — list unanswered questions\n"
        "`!answer <id> <text>` — override Tony's answer\n"
        "`!history` — last 10 Q&A entries\n"
    )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    if not Config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set.")
    bot.run(Config.DISCORD_TOKEN)
