src = open('/home/rr/Desktop/nex/nex_telegram_runner.py').read()
old = '''def run_bot():
    from telegram.ext import Application
    from nex_telegram_commands import setup_handlers

    print("[runner] Building bot application...")
    app = Application.builder().token(BOT_TOKEN).build()
    setup_handlers(app)

    print(f"[runner] Starting polling...")
    app.run_polling(
        allowed_updates=None,
        drop_pending_updates=True,
        close_loop=False,
    )'''
new = '''def run_bot():
    print("[runner] Starting nex_telegram.main()...")
    import nex_telegram
    nex_telegram.main()'''
if old in src:
    open('/home/rr/Desktop/nex/nex_telegram_runner.py', 'w').write(src.replace(old, new))
    print('done')
else:
    print('no match')
