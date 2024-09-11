from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from flask_caching import Cache
from celery import Celery
from threading import Lock
from config import Config
from flask_cors import CORS

async_mode = None
thread = None
thread_lock = Lock()
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()

def make_celery(app):
    celery_instance = Celery(
        app.import_name,
        broker=app.config['CELERY_BROKER_URL']
    )
    celery_instance.conf.update(app.config)
    return celery_instance

def create_app():
    app = Flask(__name__) # Initialize instance of Flask-APP
    app.config.from_object(Config) #Initialize default configuration for the Flask-APP
    CORS(app)
    cache = Cache(app=app)
    # Call init_app() method for SQLAlchemy, Flask Login Manager, WebSocket
    cache.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app, debug=True, cors_allowed_origins='*', logger=True, engineio_logger=True)
    login_manager.login_view = 'main.login'
    # login_manager.login_view = 'login'

    # Initialize Redis client
    #redis_client = redis.Redis(host=Config.CACHE_REDIS_HOST, port=Config.CACHE_REDIS_PORT, db=Config.CACHE_REDIS_DB)

    return app, cache

app, redis_client = create_app()
celery = make_celery(app)

from .routes import main as main_blueprint
app.register_blueprint(main_blueprint)
