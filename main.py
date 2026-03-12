import os
from flask import Flask
from flask_cors import CORS
from flask_login import LoginManager
from model.database import db
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Config
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///pwc.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Google OAuth
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# CORS — allow frontend origin
CORS(app, supports_credentials=True, origins=[
    "http://localhost:4600",
    "http://127.0.0.1:4600",
    os.environ.get("FRONTEND_URL", "http://localhost:4600"),
])

# Database
db.init_app(app)

# Login manager
login_manager = LoginManager()
login_manager.init_app(app)

from model.user import User

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
from api.auth import auth_bp
from api.admin import admin_bp
from api.events import events_bp
from api.blog import blog_bp
from api.payments import payments_bp

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(admin_bp, url_prefix="/api/admin")
app.register_blueprint(events_bp, url_prefix="/api/events")
app.register_blueprint(blog_bp, url_prefix="/api/blog")
app.register_blueprint(payments_bp, url_prefix="/api/payments")

@app.route("/api/health")
def health():
    return {"status": "ok"}

# Create tables on first run
with app.app_context():
    db.create_all()
    # Seed admin if none exists
    admin = User.query.filter_by(role="admin").first()
    if not admin:
        from werkzeug.security import generate_password_hash
        admin = User(
            username="admin",
            email="admin@powaywomansclub.org",
            password_hash=generate_password_hash("admin"),
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()
        print("Seeded default admin (username: admin, password: admin)")

if __name__ == "__main__":
    app.run(debug=True, port=5001)