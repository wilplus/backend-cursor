from flask import Flask
from flask_cors import CORS
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from config import Config

config = Config()

# Initialize Sentry
if config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
        environment=config.ENV,
    )

app = Flask(__name__)
CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)

# Register blueprints
from routes.auth import auth_bp
from routes.session import session_bp
from routes.questions import questions_bp
from routes.recordings import recordings_bp
from routes.user import user_bp

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(session_bp, url_prefix="/session")
app.register_blueprint(questions_bp, url_prefix="/questions")
app.register_blueprint(recordings_bp, url_prefix="/recordings")
app.register_blueprint(user_bp, url_prefix="/user")

@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(debug=not config.is_production, host="0.0.0.0", port=5000)
