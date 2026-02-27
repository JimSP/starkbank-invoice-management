import time
import json
import threading
import requests
from flask import Flask, jsonify, request
from ellipticcurve.ecdsa import Ecdsa
from ellipticcurve.privateKey import PrivateKey

import starkbank

from app.config import config

app = Flask(__name__)
mock_private_key, mock_public_key = starkbank.key.create()


def sign_payload(payload_string):

    with open(config.STARKBANK_PRIVATE_KEY, "r") as f:
        key_contents = f.read()

    private_key_obj = PrivateKey.fromPem(key_contents)

    return Ecdsa.sign(payload_string, private_key_obj).toBase64()


@app.route("/v2/public-key", methods=["GET"])
def get_public_key():
    """O SDK do seu app vai chamar isso para validar o Webhook."""
    return jsonify({
        "publicKeys": [{
            "content": mock_public_key,
            "id": "mock-starkbank-key"
        }]
    })


@app.route("/v2/invoice", methods=["POST"])
def create_invoice():
    """Finge criar Invoices e agenda o envio do Webhook."""
    data = request.json
    invoices = data.get("invoices", [])
    
    for i, inv in enumerate(invoices):
        inv["id"] = f"mock_inv_{int(time.time())}_{i}"
        inv["fee"] = 200
        inv["status"] = "created"

    if invoices:
        threading.Thread(target=trigger_webhook, args=(invoices[0],), daemon=True).start()

    return jsonify({"invoices": invoices})


@app.route("/v2/transfer", methods=["POST"])
def create_transfer():
    data = request.json
    transfers = data.get("transfers", [])
    
    for i, t in enumerate(transfers):
        t["id"] = f"mock_transf_{int(time.time())}_{i}"
        t["status"] = "processing"
        print(f"\n[STARK BANK MOCK] 💰 TRANSFERÊNCIA RECEBIDA! Valor: {t['amount']} para {t['name']}\n")

    return jsonify({"transfers": transfers})


def trigger_webhook(invoice):
    time.sleep(3)
    print(f"\n[STARK BANK MOCK] 📢 Alguém pagou a invoice {invoice['id']}! Enviando webhook...")
    
    payload = {
        "event": {
            "log": {
                "type": "credited",
                "invoice": invoice
            },
            "subscription": "invoice",
            "workspaceId": "mock_workspace"
        }
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    
    priv_key_obj = PrivateKey.fromPem(mock_private_key)
    signature = Ecdsa.sign(payload_str, priv_key_obj).toBase64()

    try:
        requests.post(
            "http://127.0.0.1:8080/webhook",
            data=payload_str,
            headers={"Content-Type": "application/json", "Digital-Signature": signature}
        )
    except requests.exceptions.ConnectionError:
        print("[STARK BANK MOCK] ❌ Falha ao conectar no webhook do localhost:8080")

if __name__ == "__main__":
    print("🏦 STARK BANK MOCK SERVER INICIADO NA PORTA 9090")
    app.run(host="0.0.0.0", port=9090, debug=True)