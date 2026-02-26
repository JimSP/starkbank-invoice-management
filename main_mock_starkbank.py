"""
mock_starkbank_api.py
=====================
Servidor Flask que simula a API da Stark Bank para testes locais (E2E).
Roda na porta 9090.
"""
import time
import json
import threading
import requests
from flask import Flask, jsonify, request
import ellipticcurve
import starkbank

app = Flask(__name__)

# 1. Geramos um par de chaves ECDSA exclusivas para o nosso Servidor Mock
# O mock vai assinar os webhooks com a Private, e seu app vai baixar a Public.
mock_private_key, mock_public_key = starkbank.key.create()

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
    
    # Adicionamos IDs falsos nas invoices recebidas
    for i, inv in enumerate(invoices):
        inv["id"] = f"mock_inv_{int(time.time())}_{i}"
        inv["fee"] = 200
        inv["status"] = "created"

    # Se criaram faturas, vamos fingir que a primeira foi paga 3 segundos depois
    if invoices:
        threading.Thread(target=trigger_webhook, args=(invoices[0],), daemon=True).start()

    return jsonify({"invoices": invoices})

@app.route("/v2/transfer", methods=["POST"])
def create_transfer():
    """Finge criar a Transferência recebida pelo seu app."""
    data = request.json
    transfers = data.get("transfers", [])
    
    for i, t in enumerate(transfers):
        t["id"] = f"mock_transf_{int(time.time())}_{i}"
        t["status"] = "processing"
        print(f"\n[STARK BANK MOCK] 💰 TRANSFERÊNCIA RECEBIDA! Valor: {t['amount']} para {t['name']}\n")

    return jsonify({"transfers": transfers})

def trigger_webhook(invoice):
    """Envia o webhook para o seu app (porta 8080) usando a chave do Mock."""
    time.sleep(3) # Tempo simulado do pagamento
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
    
    # Assina usando a chave PRIVADA do Mock
    priv_key_obj = ellipticcurve.privateKey.PrivateKey.fromPem(mock_private_key)
    signature = ellipticcurve.ecdsa.Ecdsa.sign(payload_str, priv_key_obj).toBase64()

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