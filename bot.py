from app.handlers import build_app

def main():
    app = build_app()
    app.run_polling(allowed_updates=None, drop_pending_updates=True)

if __name__ == "__main__":
    main()
