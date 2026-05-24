from flask import Flask, request
import requests
import os

app = Flask(__name__)

TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = "goshare123"

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
    requests.post(url, headers=headers, json=data)

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
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        from_number = message["from"]
        text = message["text"]["body"].strip()

        reponse = (
            f"🚗 Bonjour ! Bienvenue sur GoShare Conakry.\n\n"
            f"Envoyez votre trajet dans ce format :\n"
            f"*Départ → Destination*\n\n"
            f"Exemple : Ratoma → Kipé"
        )

        if "→" in text or "->" in text:
            reponse = (
                f"✅ Course reçue !\n\n"
                f"📍 Trajet : {text}\n"
                f"⏳ Un chauffeur vous confirme dans 2 minutes.\n\n"
                f"💰 Paiement : Orange Money ou cash."
            )

        send_message(from_number, reponse)
    except Exception as e:
        print(f"Erreur: {e}")

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)
