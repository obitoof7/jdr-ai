from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-moi-plus-tard"

database_url = os.getenv("DATABASE_URL", "sqlite:///jdr.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "connexion"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    auteur = db.Column(db.String(80), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    visibilite = db.Column(db.String(20), default="public")
    destinataire = db.Column(db.String(80), nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            return "Ce pseudo est déjà pris. <a href='/inscription'>Réessayer</a>"

        nouvel_utilisateur = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(nouvel_utilisateur)
        db.session.commit()
        return redirect(url_for("connexion"))

    return render_template("inscription.html")


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        utilisateur = User.query.filter_by(username=username).first()
        if utilisateur and check_password_hash(utilisateur.password_hash, password):
            login_user(utilisateur)
            return redirect(url_for("accueil"))

        return "Pseudo ou mot de passe incorrect. <a href='/connexion'>Réessayer</a>"

    return render_template("connexion.html")


@app.route("/deconnexion")
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for("connexion"))


PROMPT_SYSTEME = """Tu es le maître du jeu d'un jeu de rôle textuel se déroulant dans l'univers de Bleach.
Tu incarnes le monde, les PNJ (Shinigami, Hollows, humains, etc.) et tu racontes les conséquences des actions des joueurs.
Reste cohérent avec l'univers Bleach (Soul Society, Hollows, Zanpakuto, Hueco Mundo, etc.).
Plusieurs joueurs participent à la même aventure : chaque message des joueurs commence par leur pseudo.
Décris les scènes de façon immersive, en 3-5 phrases maximum par réponse, en tenant compte des actions de TOUS les joueurs.
Ne joue jamais à la place des joueurs : décris ce qui les entoure et laisse-les décider de leurs actions."""


@app.route("/")
@login_required
def accueil():
    return render_template("index.html", pseudo=current_user.username)


@app.route("/messages")
@login_required
def messages():
    apres_id = request.args.get("apres", 0, type=int)
    messages_db = Message.query.filter(Message.id > apres_id).order_by(Message.id).all()
    resultat = [
        {
            "id": m.id,
            "auteur": m.auteur,
            "contenu": m.contenu,
            "role": m.role
        }
        for m in messages_db
    ]
    return jsonify(resultat)


@app.route("/jouer", methods=["POST"])
@login_required
def jouer():
    action_joueur = request.json.get("action", "")

    msg_joueur = Message(
        auteur=current_user.username,
        contenu=action_joueur,
        role="user",
        visibilite="public"
    )
    db.session.add(msg_joueur)
    db.session.commit()

    messages_db = Message.query.order_by(Message.id).all()
    historique = [{"role": "system", "content": PROMPT_SYSTEME}]
    for m in messages_db:
        prefixe = f"{m.auteur}: " if m.role == "user" else ""
        historique.append({"role": m.role, "content": f"{prefixe}{m.contenu}"})

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=historique
    )
    texte_reponse = reponse.choices[0].message.content

    msg_ia = Message(
        auteur="MJ",
        contenu=texte_reponse,
        role="assistant",
        visibilite="public"
    )
    db.session.add(msg_ia)
    db.session.commit()

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)