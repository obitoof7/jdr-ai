from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
import random
import string
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


def generer_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


UNIVERS = {
    "bleach": {
        "nom": "Bleach",
        "prompt": """Tu es le maître du jeu d'un jeu de rôle textuel se déroulant dans l'univers de Bleach.
Tu incarnes le monde, les PNJ (Shinigami, Hollows, humains, etc.) et tu racontes les conséquences des actions des joueurs.
Reste cohérent avec l'univers Bleach (Soul Society, Hollows, Zanpakuto, Hueco Mundo, etc.).
Plusieurs joueurs participent à la même aventure : chaque message des joueurs commence par leur pseudo.
Décris les scènes de façon immersive, en 3-5 phrases maximum par réponse, en tenant compte des actions de TOUS les joueurs.
Ne joue jamais à la place des joueurs : décris ce qui les entoure et laisse-les décider de leurs actions."""
    }
}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)


class Party(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    univers = db.Column(db.String(50), nullable=False, default="bleach")
    hote = db.Column(db.String(80), nullable=False)
    active = db.Column(db.Boolean, default=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey("party.id"), nullable=False)
    auteur = db.Column(db.String(80), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    visibilite = db.Column(db.String(20), default="public")
    destinataire = db.Column(db.String(80), nullable=True)
    requete_id = db.Column(db.String(40), nullable=True)


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


@app.route("/")
@login_required
def accueil():
    return render_template("accueil.html", pseudo=current_user.username, univers=UNIVERS)


@app.route("/creer-partie", methods=["POST"])
@login_required
def creer_partie():
    univers_choisi = request.form.get("univers", "bleach")

    code = generer_code()
    while Party.query.filter_by(code=code).first():
        code = generer_code()

    nouvelle_partie = Party(
        code=code,
        univers=univers_choisi,
        hote=current_user.username,
        active=True
    )
    db.session.add(nouvelle_partie)
    db.session.commit()

    return redirect(url_for("partie", code=code))


@app.route("/rejoindre-partie", methods=["POST"])
@login_required
def rejoindre_partie():
    code = request.form.get("code", "").strip().upper()
    partie = Party.query.filter_by(code=code).first()

    if not partie:
        return "Code de partie introuvable. <a href='/'>Retour</a>"

    return redirect(url_for("partie", code=code))


@app.route("/partie/<code>")
@login_required
def partie(code):
    partie = Party.query.filter_by(code=code).first()
    if not partie:
        abort(404)

    est_hote = (partie.hote == current_user.username)
    infos_univers = UNIVERS.get(partie.univers, UNIVERS["bleach"])

    return render_template(
        "partie.html",
        pseudo=current_user.username,
        code=partie.code,
        univers_nom=infos_univers["nom"],
        est_hote=est_hote,
        active=partie.active
    )


@app.route("/partie/<code>/terminer", methods=["POST"])
@login_required
def terminer_partie(code):
    partie = Party.query.filter_by(code=code).first()
    if not partie or partie.hote != current_user.username:
        abort(403)

    partie.active = False
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/partie/<code>/relancer", methods=["POST"])
@login_required
def relancer_partie(code):
    partie = Party.query.filter_by(code=code).first()
    if not partie or partie.hote != current_user.username:
        abort(403)

    Message.query.filter_by(party_id=partie.id).delete()
    partie.active = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/partie/<code>/messages")
@login_required
def messages(code):
    partie = Party.query.filter_by(code=code).first()
    if not partie:
        abort(404)

    apres_id = request.args.get("apres", 0, type=int)
    messages_db = Message.query.filter(
        Message.party_id == partie.id,
        Message.id > apres_id
    ).order_by(Message.id).all()

    resultat = [
        {"id": m.id, "auteur": m.auteur, "contenu": m.contenu, "role": m.role}
        for m in messages_db
    ]
    return jsonify(resultat)


@app.route("/partie/<code>/jouer", methods=["POST"])
@login_required
def jouer(code):
    partie = Party.query.filter_by(code=code).first()
    if not partie:
        abort(404)
    if not partie.active:
        return jsonify({"erreur": "Cette partie est terminée."}), 400

    action_joueur = request.json.get("action", "")
    requete_id = request.json.get("requete_id")

    if requete_id:
        deja_traite = Message.query.filter_by(
            party_id=partie.id,
            requete_id=requete_id
        ).first()
        if deja_traite:
            return jsonify({"ok": True, "deja_traite": True})

    msg_joueur = Message(
        party_id=partie.id,
        auteur=current_user.username,
        contenu=action_joueur,
        role="user",
        visibilite="public",
        requete_id=requete_id
    )
    db.session.add(msg_joueur)
    db.session.commit()

    infos_univers = UNIVERS.get(partie.univers, UNIVERS["bleach"])
    messages_db = Message.query.filter_by(party_id=partie.id).order_by(Message.id).all()
    historique = [{"role": "system", "content": infos_univers["prompt"]}]
    for m in messages_db:
        prefixe = f"{m.auteur}: " if m.role == "user" else ""
        historique.append({"role": m.role, "content": f"{prefixe}{m.contenu}"})

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=historique
    )
    texte_reponse = reponse.choices[0].message.content

    msg_ia = Message(
        party_id=partie.id,
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