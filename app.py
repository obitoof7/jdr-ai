from flask import Flask, render_template, request, jsonify, redirect, url_for, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
import random
import string
import json
import re
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
Ne joue jamais à la place des joueurs : décris ce qui les entoure et laisse-les décider de leurs actions.
IMPORTANT: Pour chaque action d'un joueur, un résultat de jet de dé te sera donné (réussite critique, réussite, échec, ou échec critique). Tu DOIS respecter ce résultat dans ta narration : ne fais jamais réussir une action si le résultat indique un échec, et inversement.
Les personnages possèdent aussi un Reiatsu (pression/énergie spirituelle) qui reflète leur puissance spirituelle brute : utilise-le dans ta narration lors de libérations de pouvoir, de Kido, de Shikai/Bankai ou de manifestations de pression spirituelle.
IMPORTANT SUR LE PRIVÉ: certains messages sont marqués [ACTION PRIVÉE de X]. Ce sont des actions solitaires ou secrètes (fouiller seul, parler discrètement à un PNJ, etc.). Ta réponse à une action privée ne doit être connue QUE du joueur concerné : ne révèle JAMAIS dans le chat public une information qu'un joueur a obtenue uniquement en privé, sauf si ce joueur la partage lui-même publiquement dans un message ultérieur.""",
        "prompt_generation": """Génère un personnage aléatoire pour un jeu de rôle dans l'univers de Bleach.
Réponds UNIQUEMENT en JSON valide, sans aucun texte avant ou après, format exact :
{"race": "...", "classe": "...", "force": X, "agilite": X, "intelligence": X, "esprit": X, "chance": X, "reiatsu": X}
La race doit être cohérente avec Bleach (humain, Shinigami, Hollow, Quincy, etc.). La classe est son rôle/spécialité.
Le Reiatsu représente la puissance spirituelle brute du personnage (utile pour le Kido, le Shikai/Bankai, la pression spirituelle).
Chaque statistique (force, agilite, intelligence, esprit, chance, reiatsu) doit être un nombre entier entre 5 et 18."""
    }
}

MOTS_CLES_STATS = {
    "reiatsu": ["reiatsu", "kido", "kidō", "shikai", "bankai", "zanpakuto", "zanpakutô", "getsuga",
                "cero", "hollowfication", "libère son pouvoir", "libère sa pression", "pression spirituelle",
                "énergie spirituelle", "energie spirituelle"],
    "force": ["frappe", "attaque", "pousse", "soulève", "casse", "brise", "force", "combat"],
    "agilite": ["esquive", "saute", "cours", "fuis", "discrétion", "cache", "évite", "rapide"],
    "intelligence": ["analyse", "réfléchis", "comprends", "lis", "étudie", "observe", "cherche"],
    "esprit": ["perçois", "sens", "résiste", "concentre", "médite", "invoque"],
}


def deviner_stat(action_texte):
    texte = action_texte.lower()
    for stat, mots in MOTS_CLES_STATS.items():
        for mot in mots:
            if mot in texte:
                return stat
    return "chance"


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


class Personnage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey("party.id"), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    race = db.Column(db.String(80), nullable=False)
    classe = db.Column(db.String(80), nullable=False)
    force = db.Column(db.Integer, default=10)
    agilite = db.Column(db.Integer, default=10)
    intelligence = db.Column(db.Integer, default=10)
    esprit = db.Column(db.Integer, default=10)
    chance = db.Column(db.Integer, default=10)
    reiatsu = db.Column(db.Integer, default=10)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    party_id = db.Column(db.Integer, db.ForeignKey("party.id"), nullable=False)
    auteur = db.Column(db.String(80), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    visibilite = db.Column(db.String(20), default="public")
    destinataire = db.Column(db.String(80), nullable=True)
    requete_id = db.Column(db.String(40), nullable=True)
    type_special = db.Column(db.String(20), nullable=True)
    donnees_jet = db.Column(db.Text, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()
    try:
        db.session.execute(db.text("ALTER TABLE personnage ADD COLUMN reiatsu INTEGER DEFAULT 10"))
        db.session.commit()
    except Exception:
        db.session.rollback()


def generer_personnage(party_id, username, univers_cle):
    infos_univers = UNIVERS.get(univers_cle, UNIVERS["bleach"])

    try:
        reponse = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": infos_univers["prompt_generation"]}]
        )
        texte = reponse.choices[0].message.content
        match = re.search(r'\{.*\}', texte, re.DOTALL)
        data = json.loads(match.group(0))

        perso = Personnage(
            party_id=party_id,
            username=username,
            race=data.get("race", "Inconnu"),
            classe=data.get("classe", "Aventurier"),
            force=int(data.get("force", 10)),
            agilite=int(data.get("agilite", 10)),
            intelligence=int(data.get("intelligence", 10)),
            esprit=int(data.get("esprit", 10)),
            chance=int(data.get("chance", 10)),
            reiatsu=int(data.get("reiatsu", 10))
        )
    except Exception:
        perso = Personnage(
            party_id=party_id,
            username=username,
            race="Humain",
            classe="Aventurier",
            force=random.randint(8, 15),
            agilite=random.randint(8, 15),
            intelligence=random.randint(8, 15),
            esprit=random.randint(8, 15),
            chance=random.randint(8, 15),
            reiatsu=random.randint(8, 15)
        )

    db.session.add(perso)
    db.session.commit()
    return perso


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
    p = Party.query.filter_by(code=code).first()
    if not p:
        abort(404)

    est_hote = (p.hote == current_user.username)
    infos_univers = UNIVERS.get(p.univers, UNIVERS["bleach"])

    perso = Personnage.query.filter_by(party_id=p.id, username=current_user.username).first()
    if not perso:
        perso = generer_personnage(p.id, current_user.username, p.univers)

    return render_template(
        "partie.html",
        pseudo=current_user.username,
        code=p.code,
        univers_nom=infos_univers["nom"],
        est_hote=est_hote,
        active=p.active,
        perso=perso
    )


@app.route("/partie/<code>/terminer", methods=["POST"])
@login_required
def terminer_partie(code):
    p = Party.query.filter_by(code=code).first()
    if not p or p.hote != current_user.username:
        abort(403)

    p.active = False
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/partie/<code>/relancer", methods=["POST"])
@login_required
def relancer_partie(code):
    p = Party.query.filter_by(code=code).first()
    if not p or p.hote != current_user.username:
        abort(403)

    Message.query.filter_by(party_id=p.id).delete()
    Personnage.query.filter_by(party_id=p.id).delete()
    p.active = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/partie/<code>/messages")
@login_required
def messages(code):
    p = Party.query.filter_by(code=code).first()
    if not p:
        abort(404)

    apres_id = request.args.get("apres", 0, type=int)
    messages_db = Message.query.filter(
        Message.party_id == p.id,
        Message.id > apres_id
    ).order_by(Message.id).all()

    resultat = []
    for m in messages_db:
        # Un message privé n'appartenant pas au joueur courant est totalement invisible
        if m.visibilite == "prive" and m.destinataire != current_user.username:
            continue

        item = {
            "id": m.id, "auteur": m.auteur, "contenu": m.contenu,
            "role": m.role, "type_special": m.type_special,
            "canal": m.visibilite
        }
        if m.donnees_jet:
            dj = json.loads(m.donnees_jet)
            if m.visibilite == "prive":
                item["donnees_jet"] = dj
            elif dj["auteur"] == current_user.username:
                item["donnees_jet"] = dj
            else:
                item["donnees_jet"] = {"auteur": dj["auteur"], "resultat": dj["resultat"]}
        resultat.append(item)

    return jsonify(resultat)


@app.route("/partie/<code>/jouer", methods=["POST"])
@login_required
def jouer(code):
    p = Party.query.filter_by(code=code).first()
    if not p:
        abort(404)
    if not p.active:
        return jsonify({"erreur": "Cette partie est terminée."}), 400

    action_joueur = request.json.get("action", "")
    requete_id = request.json.get("requete_id")
    prive = bool(request.json.get("prive", False))

    if requete_id:
        deja_traite = Message.query.filter_by(
            party_id=p.id,
            requete_id=requete_id
        ).first()
        if deja_traite:
            return jsonify({"ok": True, "deja_traite": True})

    perso = Personnage.query.filter_by(party_id=p.id, username=current_user.username).first()

    stat_utilisee = deviner_stat(action_joueur)
    valeur_stat = getattr(perso, stat_utilisee) if perso else 10
    modificateur = round((valeur_stat - 10) / 2)

    jet = random.randint(1, 20)
    total = jet + modificateur

    if jet == 1:
        resultat = "échec critique"
    elif jet == 20:
        resultat = "réussite critique"
    elif total >= 12:
        resultat = "réussite"
    else:
        resultat = "échec"

    visibilite = "prive" if prive else "public"
    destinataire = current_user.username if prive else None

    msg_joueur = Message(
        party_id=p.id,
        auteur=current_user.username,
        contenu=action_joueur,
        role="user",
        visibilite=visibilite,
        destinataire=destinataire,
        requete_id=requete_id
    )
    db.session.add(msg_joueur)

    donnees_jet = {
        "auteur": current_user.username,
        "stat": stat_utilisee,
        "jet": jet,
        "modificateur": modificateur,
        "total": total,
        "resultat": resultat
    }
    msg_jet = Message(
        party_id=p.id,
        auteur=current_user.username,
        contenu="",
        role="jet",
        type_special="jet_de_de",
        donnees_jet=json.dumps(donnees_jet),
        visibilite=visibilite,
        destinataire=destinataire
    )
    db.session.add(msg_jet)
    db.session.commit()

    infos_univers = UNIVERS.get(p.univers, UNIVERS["bleach"])
    messages_db = Message.query.filter_by(party_id=p.id).order_by(Message.id).all()

    historique = [{"role": "system", "content": infos_univers["prompt"]}]
    for m in messages_db:
        if m.role == "jet":
            dj = json.loads(m.donnees_jet)
            note = f"[Jet de {dj['auteur']} - stat {dj['stat']}: {dj['jet']} + {dj['modificateur']} = {dj['total']} => {dj['resultat'].upper()}]"
            historique.append({"role": "system", "content": note})
        else:
            prefixe = f"{m.auteur}: " if m.role == "user" else ""
            if m.visibilite == "prive" and m.role == "user":
                prefixe = f"[ACTION PRIVÉE de {m.auteur}]: "
            historique.append({"role": m.role, "content": f"{prefixe}{m.contenu}"})

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=historique
    )
    texte_reponse = reponse.choices[0].message.content

    msg_ia = Message(
        party_id=p.id,
        auteur="MJ",
        contenu=texte_reponse,
        role="assistant",
        visibilite=visibilite,
        destinataire=destinataire
    )
    db.session.add(msg_ia)
    db.session.commit()

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)