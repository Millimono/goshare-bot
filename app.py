from flask import Flask, request
import requests
import os
import gspread
import re
from google.oauth2.service_account import Credentials
from datetime import datetime
import random
import string
from rapidfuzz import fuzz

app = Flask(__name__)

TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
VERIFY_TOKEN = "goshare123"

def get_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("/etc/secrets/credentials.json", scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.worksheet("chauffeurs"), sheet.worksheet("courses"), sheet.worksheet("sessions")

def send_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    r = requests.post(url, headers=headers, json=data)
    print(f"Send: {r.status_code}")

def nettoyer_nombre(text):
    return re.sub(r'[^\d]', '', str(text))

def to_int(val):
    try:
        return int(nettoyer_nombre(str(val)))
    except:
        return 0

def generer_code():
    return "GS-" + "".join(random.choices(string.digits, k=4))

def lire_session(sessions_sheet, numero):
    records = sessions_sheet.get_all_records()
    for row in records:
        if str(row["numero"]) == str(numero):
            return {
                "etat": str(row.get("etat", "debut")),
                "trajet": str(row.get("trajet", "")),
                "heure": str(row.get("heure", "")),
                "lieu": str(row.get("lieu", "")),
                "places": str(row.get("places", "")),
                "prix": str(row.get("prix", ""))
            }
    return {"etat": "debut", "trajet": "", "heure": "", "lieu": "", "places": "", "prix": ""}

def sauvegarder_session(sessions_sheet, numero, etat, trajet="", heure="", lieu="", places="", prix=""):
    records = sessions_sheet.get_all_records()
    data = [str(numero), str(etat), str(trajet), str(heure), str(lieu), str(places), str(prix)]
    for i, row in enumerate(records):
        if str(row["numero"]) == str(numero):
            sessions_sheet.update(f"A{i+2}:G{i+2}", [data])
            return
    sessions_sheet.append_row(data)

def ajouter_chauffeur(chauffeurs_sheet, numero, trajet, heure, lieu, places, prix):
    records = chauffeurs_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["numero"]) == str(numero):
            count = to_int(row.get("courses_count", 0))
            chauffeurs_sheet.update(f"A{i+2}:H{i+2}", [[str(numero), str(trajet), str(heure), str(lieu), "oui", str(places), str(prix), count]])
            return
    chauffeurs_sheet.append_row([str(numero), str(trajet), str(heure), str(lieu), "oui", str(places), str(prix), 0])

def trouver_chauffeurs(chauffeurs_sheet, trajet_passager):
    records = chauffeurs_sheet.get_all_records()
    resultats = []
    for i, row in enumerate(records):
        if str(row["disponible"]).lower() == "oui" and to_int(row.get("places", 0)) > 0:
            score = fuzz.ratio(trajet_passager.lower(), str(row["trajet"]).lower())
            if score >= 50:
                resultats.append((i+2, row, score))
    resultats.sort(key=lambda x: x[2], reverse=True)
    return resultats

def decrementer_place(chauffeurs_sheet, row_index):
    records = chauffeurs_sheet.get_all_records()
    row = records[row_index - 2]
    places = to_int(row.get("places", 0)) - 1
    chauffeurs_sheet.update_cell(row_index, 6, places)
    if places <= 0:
        chauffeurs_sheet.update_cell(row_index, 5, "non")

def incrementer_place(chauffeurs_sheet, row_index):
    records = chauffeurs_sheet.get_all_records()
    row = records[row_index - 2]
    places = to_int(row.get("places", 0)) + 1
    chauffeurs_sheet.update_cell(row_index, 6, places)
    chauffeurs_sheet.update_cell(row_index, 5, "oui")

def incrementer_courses(chauffeurs_sheet, row_index, prix):
    records = chauffeurs_sheet.get_all_records()
    row = records[row_index - 2]
    count = to_int(row.get("courses_count", 0)) + 1
    chauffeurs_sheet.update_cell(row_index, 8, count)
    if count == 10:
        prix_int = to_int(prix)
        commission = round(prix_int * 0.03)
        send_message(str(row["numero"]),
            f"🌟 *Félicitations et merci pour votre confiance !*\n\n"
            f"Vous venez de compléter votre *10ème course* sur GoShare Conakry.\n\n"
            f"GoShare vous a permis de trouver des passagers facilement "
            f"et de maximiser vos revenus — tout ça gratuitement.\n\n"
            f"À partir de maintenant, une commission de seulement *3%* par trajet "
            f"nous aidera à continuer cette mission ensemble.\n\n"
            f"Sur un trajet à *{prix_int:,} GNF*, cela représente *{commission:,} GNF*.\n\n"
            f"Merci de faire partie de l'aventure GoShare 🚗\n"
            f"*L'équipe GoShare Conakry*"
        )

def enregistrer_course(courses_sheet, passager, chauffeur_numero, trajet, code, row_index, prix):
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    commission = round(to_int(prix) * 0.03)
    courses_sheet.append_row([date, str(passager), str(chauffeur_numero), str(trajet), "reservee", str(code), "non", to_int(row_index), commission])

def valider_code(courses_sheet, chauffeurs_sheet, code, chauffeur_numero):
    records = courses_sheet.get_all_records()
    chauffeur_records = chauffeurs_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["code"]) == code.upper() and str(row["chauffeur"]) == str(chauffeur_numero) and str(row["validee"]) == "non":
            courses_sheet.update_cell(i+2, 7, "oui")
            courses_sheet.update_cell(i+2, 5, "confirmee")
            row_index = to_int(row.get("row_index", 0))
            prix = 0
            for c in chauffeur_records:
                if str(c["numero"]) == str(chauffeur_numero):
                    prix = c.get("prix", 0)
                    break
            if row_index > 0:
                incrementer_courses(chauffeurs_sheet, row_index, prix)
            return True, row
    return False, None

def remettre_place_si_non_validee(courses_sheet, chauffeurs_sheet, chauffeur_numero):
    records = courses_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["chauffeur"]) == str(chauffeur_numero) and str(row["validee"]) == "non" and str(row["statut"]) == "reservee":
            row_index = to_int(row.get("row_index", 0))
            if row_index > 0:
                incrementer_place(chauffeurs_sheet, row_index)
            courses_sheet.update_cell(i+2, 5, "annulee")

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Erreur", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "statuses" in entry:
            return "OK", 200
        if "messages" not in entry:
            return "OK", 200
        message = entry["messages"][0]
        if message.get("type") != "text":
            return "OK", 200

        numero = message["from"]
        text = message["text"]["body"].strip().lower()
        print(f"RECU: '{text}'")

        chauffeurs_sheet, courses_sheet, sessions_sheet = get_sheets()
        sess = lire_session(sessions_sheet, numero)
        etat = sess["etat"]
        trajet_sess = sess["trajet"]
        heure_sess = sess["heure"]
        lieu_sess = sess["lieu"]
        places_sess = sess["places"]

        print(f"SESSION: etat={etat}")

        # Commandes globales — disponibles depuis n'importe quel état
        if text == "menu":
            sauvegarder_session(sessions_sheet, numero, "attente_role")
            send_message(numero,
                "🚗 *Bienvenue sur GoShare Conakry !*\n\n"
                "Vous êtes :\n"
                "1️⃣ Tapez *chauffeur*\n"
                "2️⃣ Tapez *passager*"
            )

        elif text.startswith("valider "):
            code = text.replace("valider ", "").strip().upper()
            ok, course = valider_code(courses_sheet, chauffeurs_sheet, code, numero)
            if ok:
                send_message(numero,
                    f"✅ Code *{code}* validé !\n"
                    f"👤 Passager : +{course['passager']}\n"
                    f"📍 Trajet : {course['trajet']}"
                )
                send_message(str(course["passager"]),
                    f"✅ *Votre place est confirmée !*\n\n"
                    f"📍 Trajet : {course['trajet']}\n"
                    f"Bonne route ! 🚗"
                )
            else:
                send_message(numero, "❌ Code invalide ou déjà validé.")

        elif text == "liberer":
            remettre_place_si_non_validee(courses_sheet, chauffeurs_sheet, numero)
            send_message(numero, "✅ Places remises en disponibilité.\nTapez *menu* pour modifier.")

        elif etat in ["debut", "attente_role"] and text == "chauffeur":
            sauvegarder_session(sessions_sheet, numero, "chauffeur_trajet")
            send_message(numero,
                "✅ Bienvenue chauffeur !\n\n"
                "📍 Quel est votre trajet ?\n"
                "Exemple : *ratoma → kipé*"
            )

        elif etat in ["debut", "attente_role"] and text == "passager":
            sauvegarder_session(sessions_sheet, numero, "passager_trajet")
            send_message(numero,
                "✅ Bienvenue passager !\n\n"
                "📍 Quel est votre trajet ?\n"
                "Exemple : *ratoma - kipé*"
            )

        elif etat in ["debut", "attente_role"]:
            sauvegarder_session(sessions_sheet, numero, "attente_role")
            send_message(numero,
                "🚗 *Bienvenue sur GoShare Conakry !*\n\n"
                "Vous êtes :\n"
                "1️⃣ Tapez *chauffeur*\n"
                "2️⃣ Tapez *passager*"
            )

        elif etat == "chauffeur_trajet":
            sauvegarder_session(sessions_sheet, numero, "chauffeur_heure", trajet=text)
            send_message(numero,
                f"📍 Trajet : *{text}*\n\n"
                "⏰ Heure de départ ?\n"
                "Exemple : *08h30*"
            )

        elif etat == "chauffeur_heure":
            sauvegarder_session(sessions_sheet, numero, "chauffeur_lieu", trajet=trajet_sess, heure=text)
            send_message(numero,
                f"⏰ Heure : *{text}*\n\n"
                "📌 Lieu de départ précis ?\n"
                "Exemple : *rond point bambeto*"
            )

        elif etat == "chauffeur_lieu":
            sauvegarder_session(sessions_sheet, numero, "chauffeur_places", trajet=trajet_sess, heure=heure_sess, lieu=text)
            send_message(numero,
                f"📌 Lieu : *{text}*\n\n"
                "💺 Combien de places disponibles ?\n"
                "Exemple : *4*"
            )

        elif etat == "chauffeur_places":
            nombre = nettoyer_nombre(text)
            if nombre:
                sauvegarder_session(sessions_sheet, numero, "chauffeur_prix", trajet=trajet_sess, heure=heure_sess, lieu=lieu_sess, places=nombre)
                send_message(numero,
                    f"💺 Places : *{nombre}*\n\n"
                    "💰 Prix par place en GNF ?\n"
                    "Exemple : *15000*"
                )
            else:
                send_message(numero, "❌ Tapez un nombre. Exemple : *4*")

        elif etat == "chauffeur_prix":
            nombre = nettoyer_nombre(text)
            print(f"PRIX: nombre={nombre} trajet={trajet_sess} heure={heure_sess} lieu={lieu_sess} places={places_sess}")
            if nombre and trajet_sess and heure_sess and lieu_sess and places_sess:
                ajouter_chauffeur(chauffeurs_sheet, numero, trajet_sess, heure_sess, lieu_sess, places_sess, nombre)
                sauvegarder_session(sessions_sheet, numero, "chauffeur_pret", trajet=trajet_sess, heure=heure_sess, lieu=lieu_sess, places=places_sess, prix=nombre)
                send_message(numero,
                    f"✅ *Vous êtes enregistré !*\n\n"
                    f"📍 Trajet : *{trajet_sess}*\n"
                    f"⏰ Départ : *{heure_sess}*\n"
                    f"📌 Lieu : *{lieu_sess}*\n"
                    f"💺 Places : *{places_sess}*\n"
                    f"💰 Prix : *{nombre} GNF*\n\n"
                    "En attente de passagers... 🚗\n\n"
                    "Commandes :\n"
                    "▪️ *valider GS-XXXX* pour valider un code passager\n"
                    "▪️ *liberer* pour remettre les places non validées\n"
                    "▪️ *menu* pour modifier"
                )
            else:
                send_message(numero, "❌ Une information manque. Tapez *menu* pour recommencer.")

        elif etat == "passager_trajet":
            resultats = trouver_chauffeurs(chauffeurs_sheet, text)
            if resultats:
                msg = f"🚗 *{len(resultats)} chauffeur(s) disponible(s) :*\n\n"
                for idx, (row_index, chauffeur, score) in enumerate(resultats):
                    msg += (
                        f"{idx+1}️⃣ *{chauffeur['trajet']}*\n"
                        f"⏰ {chauffeur['heure']} — 📌 {chauffeur['lieu']}\n"
                        f"💺 {chauffeur['places']} place(s) — 💰 {chauffeur['prix']} GNF\n\n"
                    )
                msg += "Tapez le *numéro* de votre choix."
                send_message(numero, msg)
                sauvegarder_session(sessions_sheet, numero, "passager_choix", trajet=text)
            else:
                send_message(numero,
                    "⏳ Aucun chauffeur disponible.\n\n"
                    "Tapez *menu* pour recommencer."
                )
                sauvegarder_session(sessions_sheet, numero, "debut")

        elif etat == "passager_choix":
            nombre = nettoyer_nombre(text)
            if nombre:
                resultats = trouver_chauffeurs(chauffeurs_sheet, trajet_sess)
                choix = to_int(nombre) - 1
                if 0 <= choix < len(resultats):
                    row_index, chauffeur, _ = resultats[choix]
                    code = generer_code()
                    prix = chauffeur.get("prix", 0)
                    decrementer_place(chauffeurs_sheet, row_index)
                    enregistrer_course(courses_sheet, numero, chauffeur["numero"], trajet_sess, code, row_index, prix)
                    send_message(numero,
                        f"✅ *Place réservée !*\n\n"
                        f"📍 Trajet : *{chauffeur['trajet']}*\n"
                        f"⏰ Départ : *{chauffeur['heure']}*\n"
                        f"📌 Lieu : *{chauffeur['lieu']}*\n"
                        f"💰 Prix : *{prix} GNF*\n\n"
                        f"🔑 Votre code : *{code}*\n\n"
                        "Donnez ce code au chauffeur pour confirmer votre place.\n"
                        "⚠️ Si non validé avant le départ, votre place sera libérée."
                    )
                    send_message(str(chauffeur["numero"]),
                        f"🎉 *Nouveau passager !*\n\n"
                        f"📍 Trajet : *{trajet_sess}*\n"
                        f"💰 Prix : *{prix} GNF*\n"
                        f"💺 Places restantes : *{to_int(chauffeur['places'])-1}*\n\n"
                        "Tapez *valider GS-XXXX* quand le passager vous donne son code."
                    )
                    sauvegarder_session(sessions_sheet, numero, "debut")
                else:
                    send_message(numero, "❌ Numéro invalide.")
            else:
                send_message(numero, "❌ Tapez le numéro. Exemple : *1*")

    except Exception as e:
        print(f"Erreur: {e}")

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)