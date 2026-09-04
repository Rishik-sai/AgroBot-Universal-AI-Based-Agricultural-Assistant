"""Production WSGI entry point.

`app.py` only bootstraps the database and static files under `__main__`, which
gunicorn never executes -- so we do it here, once, at import time.
"""
from app import app, socketio, init_database, create_missing_files

create_missing_files()
init_database()

# gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker wsgi:app
application = app

if __name__ == "__main__":
    import os
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)),
                 allow_unsafe_werkzeug=True)
