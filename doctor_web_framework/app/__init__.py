from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_caching import Cache
from threading import Lock, Thread, Event
from typing import Dict, List
from config import Config

# user_threads:Dict[str, Dict[str, Thread]] = {}
user_threads:Dict[str, Thread] = {}
stop_signals:Dict[str, Event] = {}
patients_session:Dict[str, List] = {}
thread_lock = Lock()
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()
user_sessions = {}

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config) #Initialize default configuration for the Flask-APP
    cache = Cache(app=app)
    # Call init_app() method for SQLAlchemy, Flask Login Manager, WebSocket
    cache.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, debug=True, cors_allowed_origins='*', logger=True, engineio_logger=True)
    login_manager.login_view = 'main.login'

    # Initialize Redis client
    #redis_client = redis.Redis(host=Config.CACHE_REDIS_HOST, port=Config.CACHE_REDIS_PORT, db=Config.CACHE_REDIS_DB)

    return app, cache

app, redis_client = create_app()

from .routes import main as main_blueprint
app.register_blueprint(main_blueprint)
