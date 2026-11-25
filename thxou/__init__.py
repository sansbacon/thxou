from flask import Flask
from .config import Config
from .routes import bp


def create_app(config=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    app.register_blueprint(bp)
    return app
