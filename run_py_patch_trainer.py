"""
run.py patch — add NEX self-training watermark check to the cycle loop
=======================================================================

1. Near the TOP of run.py, after the existing imports, add a helper
   that grabs the Telegram send function so the trainer can message you:

────────────────────────────────────────────────────────────────────────
# ── Training watermark send helper ───────────────────────────────────
def _get_tg_send_fn():
    \"\"\"Returns a callable that sends a Telegram message to the owner.\"\"\"
    try:
        from nex_telegram_commands import OWNER_TELEGRAM_ID
        from nex_telegram import BOT_TOKEN
        import requests as _r
        def _send(text):
            _r.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": OWNER_TELEGRAM_ID, "text": text,
                      "parse_mode": "Markdown"},
                timeout=10
            )
        return _send
    except Exception:
        return None
────────────────────────────────────────────────────────────────────────


2. Inside the CYCLE loop, after the existing BELIEF DECAY block
   (around line 1446 in your current run.py), add this block:

────────────────────────────────────────────────────────────────────────
                        # ── SELF-TRAINING WATERMARK CHECK ─────────────
                        try:
                            from nex_self_trainer import check_training_watermark
                            check_training_watermark(
                                cycle,
                                send_telegram_fn=_get_tg_send_fn()
                            )
                        except Exception as _ste:
                            pass
────────────────────────────────────────────────────────────────────────


3. Inside the Telegram handle_message function in nex_telegram.py,
   BEFORE the normal "ask_nex" reply, add this block so /light /medium
   /heavy /havok /notrain are intercepted:

────────────────────────────────────────────────────────────────────────
    # ── Training approval commands ───────────────────────────────────
    from nex_self_trainer import TRAIN_COMMANDS, handle_training_command
    cmd_word = user_message.strip().lower().split()[0] if user_message.strip() else ""
    if cmd_word in TRAIN_COMMANDS:
        from nex_telegram_commands import OWNER_TELEGRAM_ID
        if user_id == OWNER_TELEGRAM_ID:
            async def _send_fn(msg):
                await update.message.reply_text(msg)
            # handle_training_command is sync but spawns a thread — wrap it
            import asyncio, functools
            loop = asyncio.get_event_loop()
            send_sync = lambda msg: asyncio.run_coroutine_threadsafe(
                update.message.reply_text(msg), loop
            )
            handle_training_command(user_message.strip(), send_sync)
            return
────────────────────────────────────────────────────────────────────────


HOW THE FULL FLOW WORKS
=======================

Every 10 cycles (~20 min), check_training_watermark() queries the DB:

  Threshold      New beliefs    Avg confidence
  ─────────────────────────────────────────────
  light          2,000+         52%+
  medium         5,000+         57%+
  heavy          9,000+         62%+
  havok          15,000+        67%+

When a threshold is crossed, NEX sends you a Telegram message:

  🧠 NEX Training Proposal
  📊 Beliefs collected: 9,206
     New since last run: 5,100
     Avg confidence: 63%
     High-quality (70%+): 1,840
     Topics covered: 151

  💡 Suggested: HEAVY
     Deep absorption. Noticeable personality shift.

  🟢 /light   — 1 epoch  · safe       · ~45 min
  🟡 /medium  — 2 epochs · balanced   · ~90 min
  🔴 /heavy   — 3 epochs · deep       · ~3 hrs
  ☢️ /havok   — 5 epochs · aggressive · ~6 hrs
  /notrain — skip this round

You reply. NEX trains in the background, sends progress updates,
merges her adapter into Qwen2.5-3B, converts to GGUF, and restarts
llama-server with her own trained weights.

WATERMARK RESET
===============
After each training run, the belief count at that moment is stored in
~/.config/nex/trainer_state.json as last_trained_belief_count.
The next proposal only fires when NEW_beliefs (total - last count)
crosses the next threshold. So she can't spam you.
"""
