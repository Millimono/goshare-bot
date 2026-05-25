from flask import Flask, request
import requests
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from rapidfuzz import fuzz

app = Flask(__name__)

TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
VERIFY_TOKEN = "goshare123"

sessions = {}

def get_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("/etc/secrets/credentials.json", scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.worksheet("chauffeurs"), sheet.worksheet("courses")

def send_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    r = requests.post(url, headers=headers, json=data)
    print(f"Send message response: {r.status_code} {r.text}")

def ajouter_chauffeur(numero, trajet, heure, lieu):
    chauffeurs_sheet, _ = get_sheets()
    records = chauffeurs_sheet.get_all_records()
    for i, row in enumerate(records):
        if str(row["numero"]) == str(numero):
            chauffeurs_sheet.update(f"A{i+2}:E{i+2}", [[numero, trajet, heure, lieu, "oui"]])
            return
    chauffeurs_sheet.append_row([numero, trajet, heure, lieu, "oui"])

def trouver_chauffeurs(trajet_passager):
    chauffeurs_sheet, _ = get_sheets()
    records = chauffeurs_sheet.get_all_records()
    resultats = []

    for i, row in enumerate(records):
        if str(row["disponible"]).lower() == "oui":
            score = fuzz.ratio(
                trajet_passager.lower(),
                str(row["trajet"]).lower()
            )
            if score >= 50:
                resultats.append((i+2, row, score))

    # Trier par score décroissant
    resultats.sort(key=lambda x: x[2], reverse=True)
    return resultats

def marquer_indisponible(row_index):
    chauffeurs_sheet, _ = get_sheets()
    chauffeurs_sheet.update_cell(row_index, 5, "non")

def enregistrer_course(passager, chauffeur, trajet):
    _, courses_sheet = get_sheets()
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    courses_sheet.append_row([date, passager, chauffeur, trajet, "confirmée"])

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
        etat = sessions.get(numero, "debut")

        if text == "menu":
            sessions[numero] = "debut"
            etat = "debut"

        if etat == "debut":
            send_message(numero,
                "🚗 *Bienvenue sur GoShare Conakry !*\n\n"
                "Vous êtes :\n"
                "1️⃣ Tapez *chauffeur*\n"
                "2️⃣ Tapez *passager*"
            )
            sessions[numero] = "attente_role"

        elif etat == "attente_role":
            if text == "chauffeur":
                sessions[numero] = "chauffeur_trajet"
                send_message(numero,
                    "✅ Bienvenue chauffeur !\n\n"
                    "📍 Quel est votre trajet ?\n"
                    "Exemple : *ratoma → kipé*"
                )
            elif text == "passager":
                sessions[numero] = "passager_trajet"
                send_message(numero,
                    "✅ Bienvenue passager !\n\n"
                    "📍 Quel est votre trajet ?\n"
                    "Exemple : *ratoma - kipé*"
                )
            else:
                send_message(numero, "❌ Tapez *chauffeur* ou *passager* uniquement.")

        elif etat == "chauffeur_trajet":
            sessions[numero + "_trajet"] = text
            sessions[numero] = "chauffeur_heure"
            send_message(numero,
                f"📍 Trajet : *{text}*\n\n"
                "⏰ Heure de départ ?\n"
                "Exemple : *08h30*"
            )

        elif etat == "chauffeur_heure":
            sessions[numero + "_heure"] = text
            sessions[numero] = "chauffeur_lieu"
            send_message(numero,
                f"⏰ Heure : *{text}*\n\n"
                "📌 Lieu de départ précis ?\n"
                "Exemple : *rond point bambeto*"
            )

        elif etat == "chauffeur_lieu":
            trajet = sessions.get(numero + "_trajet", "")
            heure = sessions.get(numero + "_heure", "")
            ajouter_chauffeur(numero, trajet, heure, text)
            sessions[numero] = "chauffeur_pret"
            send_message(numero,
                f"✅ *Vous êtes enregistré !*\n\n"
                f"📍 Trajet : *{trajet}*\n"
                f"⏰ Départ : *{heure}*\n"
                f"📌 Lieu : *{text}*\n\n"
                "En attente de passagers... 🚗\n"
                "Tapez *menu* pour modifier."
            )

        elif etat == "passager_trajet":
            trajet = text
            resultats = trouver_chauffeurs(trajet)

            if resultats:
                # Construire message avec tous les chauffeurs
                msg = f"🚗 *{len(resultats)} chauffeur(s) disponible(s) pour votre trajet :*\n\n"
                for idx, (row_index, chauffeur, score) in enumerate(resultats):
                    msg += (
                        f"{idx+1}️⃣ *{chauffeur['trajet']}*\n"
                        f"⏰ {chauffeur['heure']} — 📌 {chauffeur['lieu']}\n\n"
                    )
                msg += "Tapez le *numéro* de votre choix."

                send_message(numero, msg)
                sessions[numero] = "passager_choix"
                sessions[numero + "_resultats"] = resultats
                sessions[numero + "_trajet"] = trajet

            else:
                send_message(numero,
                    f"⏳ Aucun chauffeur disponible pour *{trajet}*.\n\n"
                    "Réessayez dans quelques minutes.\n"
                    "Tapez *menu* pour recommencer."
                )
                sessions[numero] = "debut"

        elif etat == "passager_choix":
            resultats = sessions.get(numero + "_resultats", [])
            trajet = sessions.get(numero + "_trajet", "")

            try:
                choix = int(text) - 1
                if 0 <= choix < len(resultats):
                    row_index, chauffeur, _ = resultats[choix]
                    marquer_indisponible(row_index)
                    enregistrer_course(numero, chauffeur["numero"], trajet)

                    send_message(numero,
                        f"✅ *Course confirmée !*\n\n"
                        f"📍 Trajet : *{chauffeur['trajet']}*\n"
                        f"⏰ Départ : *{chauffeur['heure']}*\n"
                        f"📌 Lieu de rendez-vous : *{chauffeur['lieu']}*\n\n"
                        f"💰 Paiement : Orange Money ou cash.\n"
                        f"Bonne route ! 🚗"
                    )
                    send_message(str(chauffeur["numero"]),
                        f"🎉 *Nouveau passager !*\n\n"
                        f"📍 Trajet : *{trajet}*\n"
                        f"👤 Contact : +{numero}\n\n"
                        f"Bonne route ! 🚗"
                    )
                    sessions[numero] = "debut"
                else:
                    send_message(numero, "❌ Numéro invalide. Tapez le numéro de votre choix.")
            except:
                send_message(numero, "❌ Tapez juste le numéro de votre choix. Ex : *1*")

    except Exception as e:
        print(f"Erreur: {e}")

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)
