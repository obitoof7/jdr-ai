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

ZONE_DEFAUT = "Ensemble"
BALISE_MONTEE = "[MONTEE_DE_NIVEAU]"


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
IMPORTANT SUR LE PRIVÉ: certains messages sont marqués [ACTION PRIVÉE de X]. Ce sont des actions solitaires ou secrètes. Ta réponse à une action privée ne doit être connue QUE du joueur concerné : ne révèle JAMAIS dans le chat public une information qu'un joueur a obtenue uniquement en privé, sauf si ce joueur la partage lui-même publiquement.
IMPORTANT SUR LA PROGRESSION: si, et seulement si, l'action du joueur qui vient d'agir représente un accomplissement réellement marquant et rare (victoire décisive contre un adversaire nettement supérieur, moment charnière de développement du personnage, réussite critique dans un instant crucial), termine ta réponse par la balise exacte [MONTEE_DE_NIVEAU] sur sa propre ligne. N'utilise cette balise que très rarement, seulement pour un vrai tournant.
IMPORTANT SUR LES POINTS DE VIE: si l'action du joueur implique qu'il encaisse un coup, une blessure, ou tout dommage physique/spirituel cohérent avec le résultat du jet (surtout en cas d'échec ou échec critique lors d'un combat), ajoute la balise [DEGATS:X] où X est un nombre entre 1 et 25 reflétant la gravité (léger pour un échec simple, sévère pour un échec critique face à un adversaire puissant). Si le joueur se soigne, reçoit des soins d'un allié/Kido de soin, ou se repose, ajoute plutôt [SOIN:X] avec X entre 1 et 20. N'ajoute JAMAIS ces balises pour une action anodine sans enjeu physique. Tu peux combiner plusieurs balises si pertinent.""",
        "races": {
            "Humain": [
                {"classe": "Étudiant ordinaire", "stats": (5, 10), "reiatsu": (3, 7)},
            ],
            "Shinigami": [
                {"classe": "Recrue de l'Académie", "stats": (6, 11), "reiatsu": (6, 11)},
                {"classe": "Simple officier de division", "stats": (9, 14), "reiatsu": (9, 14)},
                {"classe": "Lieutenant de division", "stats": (12, 16), "reiatsu": (13, 17)},
                {"classe": "Capitaine de division", "stats": (15, 18), "reiatsu": (16, 18)},
            ],
            "Hollow": [
                {"classe": "Hollow ordinaire", "stats": (9, 14), "reiatsu": (9, 15)},
                {"classe": "Adjuchas", "stats": (12, 16), "reiatsu": (13, 17)},
                {"classe": "Vasto Lorde", "stats": (15, 18), "reiatsu": (16, 18)},
            ],
            "Arrancar": [
                {"classe": "Fraccion", "stats": (10, 14), "reiatsu": (10, 15)},
                {"classe": "Numeros", "stats": (12, 16), "reiatsu": (13, 17)},
                {"classe": "Espada", "stats": (15, 18), "reiatsu": (16, 18)},
            ],
            "Quincy": [
                {"classe": "Quincy autodidacte", "stats": (6, 11), "reiatsu": (6, 11)},
                {"classe": "Archer Quincy traditionnel", "stats": (9, 14), "reiatsu": (9, 14)},
                {"classe": "Sternritter", "stats": (15, 18), "reiatsu": (15, 18)},
            ],
            "Fullbringer": [
                {"classe": "Fullbringer novice", "stats": (6, 11), "reiatsu": (5, 10)},
                {"classe": "Ancien Xcution", "stats": (10, 14), "reiatsu": (10, 15)},
            ],
            "Vizard": [
                {"classe": "Vizard en formation", "stats": (12, 16), "reiatsu": (12, 16)},
                {"classe": "Ancien capitaine devenu Vizard", "stats": (15, 18), "reiatsu": (16, 18)},
            ],
        }
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


def liste_plate_archetypes(univers_cle):
    infos = UNIVERS.get(univers_cle, UNIVERS["bleach"])
    plate = []
    for race, paliers in infos["races"].items():
        for palier in paliers:
            plate.append({"race": race, **palier})
    return plate


def calculer_pv_max(stat_min, stat_max):
    return round(((stat_min + stat_max) / 2) * 3)


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
    zone = db.Column(db.String(80), default=ZONE_DEFAUT)
    pv_max = db.Column(db.Integer, default=20)
    pv_actuels = db.Column(db.Integer, default=20)


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
    for ddl in [
        "ALTER TABLE personnage ADD COLUMN reiatsu INTEGER DEFAULT 10",
        f"ALTER TABLE personnage ADD COLUMN zone VARCHAR(80) DEFAULT '{ZONE_DEFAUT}'",
        "ALTER TABLE personnage ADD COLUMN pv_max INTEGER DEFAULT 20",
        "ALTER TABLE personnage ADD COLUMN pv_actuels INTEGER DEFAULT 20",
    ]:
        try:
            db.session.execute(db.text(ddl))
            db.session.commit()
        except Exception:
            db.session.rollback()


def modificateur_de(valeur):
    return round((valeur - 10) / 2)


def generer_personnage(party_id, username, univers_cle):
    archetype = random.choice(liste_plate_archetypes(univers_cle))

    stat_min, stat_max = archetype["stats"]
    reiatsu_min, reiatsu_max = archetype["reiatsu"]
    pv_max = calculer_pv_max(stat_min, stat_max)

    perso = Personnage(
        party_id=party_id,
        username=username,
        race=archetype["race"],
        classe=archetype["classe"],
        force=random.randint(stat_min, stat_max),
        agilite=random.randint(stat_min, stat_max),
        intelligence=random.randint(stat_min, stat_max),
        esprit=random.randint(stat_min, stat_max),
        chance=random.randint(stat_min, stat_max),
        reiatsu=random.randint(reiatsu_min, reiatsu_max),
        zone=ZONE_DEFAUT,
        pv_max=pv_max,
        pv_actuels=pv_max
    )

    db.session.add(perso)
    db.session.commit()
    return perso


def evoluer_personnage(perso, univers_cle):
    races = UNIVERS.get(univers_cle, UNIVERS["bleach"])["races"]

    if perso.race == "Humain":
        autres_races = [r for r in races.keys() if r != "Humain"]
        nouvelle_race = random.choice(autres_races)
        premier_palier = races[nouvelle_race][0]

        ancienne_race, ancienne_classe = perso.race, perso.classe
        perso.race = nouvelle_race
        perso.classe = premier_palier["classe"]

        stat_min, stat_max = premier_palier["stats"]
        reiatsu_min, reiatsu_max = premier_palier["reiatsu"]
        for stat_nom in ["force", "agilite", "intelligence", "esprit", "chance"]:
            valeur_actuelle = getattr(perso, stat_nom)
            perso.__setattr__(stat_nom, max(valeur_actuelle, random.randint(stat_min, stat_max)))
        perso.reiatsu = max(perso.reiatsu, random.randint(reiatsu_min, reiatsu_max))

        nouveau_pv_max = calculer_pv_max(stat_min, stat_max)
        if nouveau_pv_max > perso.pv_max:
            diff = nouveau_pv_max - perso.pv_max
            perso.pv_max = nouveau_pv_max
            perso.pv_actuels = min(perso.pv_max, perso.pv_actuels + diff)

        db.session.commit()
        return f"{ancienne_race} ({ancienne_classe}) → {nouvelle_race} ({perso.classe})"

    palier_liste = races.get(perso.race, [])
    index_actuel = next((i for i, pl in enumerate(palier_liste) if pl["classe"] == perso.classe), None)

    if index_actuel is None or index_actuel + 1 >= len(palier_liste):
        return None

    nouveau_palier = palier_liste[index_actuel + 1]
    ancienne_classe = perso.classe
    perso.classe = nouveau_palier["classe"]

    stat_min, stat_max = nouveau_palier["stats"]
    reiatsu_min, reiatsu_max = nouveau_palier["reiatsu"]
    for stat_nom in ["force", "agilite", "intelligence", "esprit", "chance"]:
        valeur_actuelle = getattr(perso, stat_nom)
        perso.__setattr__(stat_nom, max(valeur_actuelle, random.randint(stat_min, stat_max)))
    perso.reiatsu = max(perso.reiatsu, random.randint(reiatsu_min, reiatsu_max))

    nouveau_pv_max = calculer_pv_max(stat_min, stat_max)
    if nouveau_pv_max > perso.pv_max:
        diff = nouveau_pv_max - perso.pv_max
        perso.pv_max = nouveau_pv_max
        perso.pv_actuels = min(perso.pv_max, perso.pv_actuels + diff)

    db.session.commit()
    return f"{ancienne_classe} → {perso.classe}"


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
    mes_persos = Personnage.query.filter_by(username=current_user.username).all()
    party_ids = [p.party_id for p in mes_persos]
    mes_parties = []
    if party_ids:
        parties_db = Party.query.filter(Party.id.in_(party_ids)).order_by(Party.id.desc()).all()
        for p in parties_db:
            infos_univers = UNIVERS.get(p.univers, UNIVERS["bleach"])
            mes_parties.append({
                "code": p.code,
                "univers_nom": infos_univers["nom"],
                "active": p.active,
                "est_hote": p.hote == current_user.username
            })

    return render_template("accueil.html", pseudo=current_user.username, univers=UNIVERS, mes_parties=mes_parties)


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


@app.route("/partie/<code>/zone", methods=["POST"])
@login_required
def changer_zone(code):
    p = Party.query.filter_by(code=code).first()
    if not p:
        abort(404)

    nouvelle_zone = request.json.get("zone", "").strip()
    if not nouvelle_zone:
        return jsonify({"erreur": "Zone vide"}), 400

    perso = Personnage.query.filter_by(party_id=p.id, username=current_user.username).first()
    if perso:
        perso.zone = nouvelle_zone[:80]
        db.session.commit()

    return jsonify({"ok": True, "zone": perso.zone})


@app.route("/partie/<code>/personnage")
@login_required
def infos_personnage(code):
    p = Party.query.filter_by(code=code).first()
    if not p:
        abort(404)
    perso = Personnage.query.filter_by(party_id=p.id, username=current_user.username).first()
    if not perso:
        abort(404)
    return jsonify({
        "race": perso.race, "classe": perso.classe,
        "force": perso.force, "agilite": perso.agilite, "intelligence": perso.intelligence,
        "esprit": perso.esprit, "chance": perso.chance, "reiatsu": perso.reiatsu, "zone": perso.zone,
        "pv_max": perso.pv_max, "pv_actuels": perso.pv_actuels
    })


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
        if m.visibilite == "prive" and m.destinataire != current_user.username:
            continue

        item = {
            "id": m.id, "auteur": m.auteur, "contenu": m.contenu,
            "role": m.role, "type_special": m.type_special
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


def tenter_perceptions(p, acteur_username, acteur_perso, action_texte):
    if not acteur_perso:
        return

    autres = Personnage.query.filter(
        Personnage.party_id == p.id,
        Personnage.username != acteur_username,
        Personnage.zone == acteur_perso.zone
    ).all()

    mod_discretion = modificateur_de(acteur_perso.agilite)
    difficulte = 12 + mod_discretion

    for observateur in autres:
        mod_esprit = modificateur_de(observateur.esprit)
        jet_perception = random.randint(1, 20)
        total_perception = jet_perception + mod_esprit

        if jet_perception != 1 and (jet_perception == 20 or total_perception >= difficulte):
            indice = f"Tu remarques que {acteur_username} agit étrangement, à l'écart, mais tu ne distingues pas exactement quoi."
            msg_perception = Message(
                party_id=p.id,
                auteur="MJ",
                contenu=indice,
                role="assistant",
                visibilite="prive",
                destinataire=observateur.username,
                type_special="perception"
            )
            db.session.add(msg_perception)

    db.session.commit()


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
    modificateur = modificateur_de(valeur_stat)

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

    if prive:
        tenter_perceptions(p, current_user.username, perso, action_joueur)

    infos_univers = UNIVERS.get(p.univers, UNIVERS["bleach"])
    messages_db = Message.query.filter_by(party_id=p.id).order_by(Message.id).all()

    historique = [{"role": "system", "content": infos_univers["prompt"]}]
    for m in messages_db:
        if m.type_special == "perception":
            continue
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

    montee_de_niveau = BALISE_MONTEE in texte_reponse
    degats_match = re.search(r"\[DEGATS:(\d+)\]", texte_reponse, re.IGNORECASE)
    soin_match = re.search(r"\[SOIN:(\d+)\]", texte_reponse, re.IGNORECASE)

    texte_reponse_propre = texte_reponse
    for balise in [BALISE_MONTEE, degats_match.group(0) if degats_match else "", soin_match.group(0) if soin_match else ""]:
        if balise:
            texte_reponse_propre = texte_reponse_propre.replace(balise, "")
    texte_reponse_propre = texte_reponse_propre.strip()

    msg_ia = Message(
        party_id=p.id,
        auteur="MJ",
        contenu=texte_reponse_propre,
        role="assistant",
        visibilite=visibilite,
        destinataire=destinataire
    )
    db.session.add(msg_ia)
    db.session.commit()

    if perso:
        if degats_match:
            valeur = max(1, min(25, int(degats_match.group(1))))
            perso.pv_actuels = max(0, perso.pv_actuels - valeur)
            texte_pv = f"💥 {current_user.username} perd {valeur} PV ({perso.pv_actuels}/{perso.pv_max})"
            if perso.pv_actuels == 0:
                texte_pv += " — K.O. !"
            db.session.add(Message(
                party_id=p.id, auteur="Système", contenu=texte_pv,
                role="assistant", visibilite="public", type_special="pv_change"
            ))
            db.session.commit()

        if soin_match:
            valeur = max(1, min(20, int(soin_match.group(1))))
            perso.pv_actuels = min(perso.pv_max, perso.pv_actuels + valeur)
            texte_pv = f"❤️‍🩹 {current_user.username} récupère {valeur} PV ({perso.pv_actuels}/{perso.pv_max})"
            db.session.add(Message(
                party_id=p.id, auteur="Système", contenu=texte_pv,
                role="assistant", visibilite="public", type_special="pv_change"
            ))
            db.session.commit()

        if montee_de_niveau:
            description_evolution = evoluer_personnage(perso, p.univers)
            if description_evolution:
                db.session.add(Message(
                    party_id=p.id, auteur="Système",
                    contenu=f"⬆️ {current_user.username} évolue : {description_evolution} !",
                    role="assistant", visibilite="public", type_special="evolution"
                ))
                db.session.commit()

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)