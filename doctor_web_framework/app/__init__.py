from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_caching import Cache
from threading import Lock, Thread, Event
from typing import Dict, List, Tuple
from config import Config
import logging
from logging.handlers import RotatingFileHandler
import sys

# user_threads:Dict[str, Dict[str, Thread]] = {}
user_threads:Dict[str, Thread] = {}
stop_signals:Dict[str, Event] = {}
patients_session:Dict[str, List] = {}
thread_lock = Lock()
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()
user_sessions = {}

def create_app()->Tuple[Flask,Cache,logging.Logger]:
    app = Flask(__name__)
    app.config.from_object(Config) #Initialize default configuration for the Flask-APP
    cache = Cache(app=app)
    # Call init_app() method for SQLAlchemy, Flask Login Manager, WebSocket
    cache.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, cors_allowed_origins='*', logger=True, engineio_logger=True)
    login_manager.login_view = 'main.login'

    log_file = './logs/app.log'
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = logging.INFO
    file_handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
    file_handler.setLevel(log_level)
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.addHandler(file_handler)
    logger.setLevel(log_level)

    # logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    # logger = logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    # Initialize Redis client
    #redis_client = redis.Redis(host=Config.CACHE_REDIS_HOST, port=Config.CACHE_REDIS_PORT, db=Config.CACHE_REDIS_DB)

    return app, cache, logger

app, redis_client, logger = create_app()

from .routes import main as main_blueprint
app.register_blueprint(main_blueprint)
