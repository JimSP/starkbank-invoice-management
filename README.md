# Stark Bank – Back End Developer Trial

Integração Python com a API da Stark Bank que emite Invoices periodicamente e
encaminha os pagamentos recebidos via Transfer.

---

## Stack de bibliotecas

| Biblioteca | Papel |
|---|---|
| [`starkbank`](https://github.com/starkbank/sdk-python) | SDK principal — `invoice`, `transfer`, `webhook`, `event` |
| [`starkbank-ecdsa`](https://github.com/starkbank/ecdsa-python) | Geração e assinatura de chaves secp256k1 (via `starkbank.key`) |
| [`starkcore`](https://github.com/starkbank/core-python) | Camada HTTP + autenticação (dependência interna do SDK) |
| `Flask` | Servidor web para receber callbacks do webhook |
| `APScheduler` | Agendador em background thread |

---

## Arquitetura da solução

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│                                                             │
│   ┌─────────────────┐         ┌─────────────────────────┐  │
│   │   Scheduler      │         │   Flask (webhook server) │  │
│   │  (background     │         │                         │  │
│   │   thread)        │         │   GET  /health           │  │
│   │                 │         │   POST /webhook          │  │
│   │  every 3h ──────┼────┐    └────────────┬────────────┘  │
│   └─────────────────┘    │                 │               │
│                           │                 │               │
└───────────────────────────┼─────────────────┼───────────────┘
                            │                 │
                            ▼                 ▼
              ┌─────────────────┐   ┌──────────────────────┐
              │  invoices.py    │   │    webhook.py         │
              │                 │   │                       │
              │  starkbank      │   │  starkbank            │
              │  .invoice       │   │  .event.parse()       │
              │  .create()      │   │  (verifica ECDSA)     │
              └────────┬────────┘   └──────────┬───────────┘
                       │                        │
                       ▼                        ▼ log.type == "credited"
              ┌─────────────────┐   ┌──────────────────────┐
              │  Stark Bank API │   │   transfers.py        │
              │  (Sandbox)      │   │                       │
              │                 │   │  starkbank            │
              │  auto-pays some │   │  .transfer.create()   │
              │  invoices  ─────┼──►│                       │
              └─────────────────┘   └──────────────────────┘
```

---

## Fluxo de dados — sequência completa

```
 App                    Stark Bank API            Stark Bank Sandbox
  │                          │                           │
  │── starkbank.invoice ─────►│                           │
  │   .create([8..12])        │                           │
  │◄── invoices criadas ──────│                           │
  │                           │                           │
  │         (a cada 3h por 24h, acima se repete)          │
  │                           │                           │
  │                           │◄── pagamento automático ──│
  │                           │    (Sandbox paga          │
  │                           │     algumas invoices)     │
  │                           │                           │
  │◄── POST /webhook ─────────│                           │
  │    Digital-Signature: xyz  │                           │
  │    { subscription:         │                           │
  │      "invoice",            │                           │
  │      log.type:             │                           │
  │      "credited",           │                           │
  │      invoice.amount: N,    │                           │
  │      invoice.fee: F }      │                           │
  │                           │                           │
  │  starkbank.event.parse()   │                           │
  │  (verifica assinatura)     │                           │
  │                           │                           │
  │── starkbank.transfer ─────►│                           │
  │   .create([amount=N-F])    │                           │
  │   → Stark Bank S.A.        │                           │
  │                           │                           │
  │── HTTP 200 ───────────────►│                           │
```

---

## Verificação de assinatura (sem código manual)

O SDK usa `starkbank-ecdsa` internamente para **verificar** cada callback:

```python
event = starkbank.event.parse(
    content=request.data.decode("utf-8"),
    signature=request.headers.get("Digital-Signature", ""),
)
# ↑ busca a chave pública da Stark Bank automaticamente
# ↑ lança InvalidSignatureError se inválida
```

E para **gerar** o seu par de chaves antes de criar o Projeto:

```python
# keygen.py usa starkbank.key (que chama starkbank-ecdsa internamente)
private_key, public_key = starkbank.key.create()
```

---

## Estrutura do projeto

```
starkbank-trial/
│
├── app/                        ← pacote principal
│   ├── __init__.py
│   ├── config.py               ← credenciais + init_starkbank()
│   ├── people.py               ← gerador de pagadores aleatórios (CPF válido)
│   ├── invoices.py             ← emissão de lote via starkbank.invoice.create()
│   ├── transfers.py            ← repasse via starkbank.transfer.create()
│   ├── scheduler.py            ← APScheduler: dispara a cada 3h por 24h
│   └── webhook.py              ← Flask: POST /webhook + GET /health
│
├── tests/                      ← 100% de cobertura
│   ├── conftest.py             ← fixtures compartilhadas (Flask test client)
│   ├── test_config.py
│   ├── test_people.py
│   ├── test_invoices.py
│   ├── test_transfers.py
│   ├── test_scheduler.py
│   └── test_webhook.py
│
├── main.py                     ← entry point (scheduler + Flask juntos)
├── keygen.py                   ← gera par de chaves ECDSA
├── setup_webhook.py            ← registra webhook na Stark Bank (1x)
├── Dockerfile
├── pytest.ini                  ← --cov=app --cov-fail-under=100
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Gerar par de chaves ECDSA

```bash
python keygen.py keys/
# Salva keys/privateKey.pem e keys/publicKey.pem
```

Faça upload da **chave pública** no painel Sandbox:
`Menu → Integrações → Novo Projeto → cole o conteúdo de publicKey.pem`

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com seu PROJECT_ID e PRIVATE_KEY
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Registrar o webhook (uma vez)

```bash
# Localmente com ngrok:
ngrok http 8080
python setup_webhook.py https://abc123.ngrok.io/webhook

# Ou com a URL de produção após deploy:
python setup_webhook.py https://sua-app.run.app/webhook
```

### 5. Executar

```bash
python main.py
```

---

## Testes e cobertura

```bash
pytest
```

```
Name               Stmts   Miss  Cover
--------------------------------------
app/__init__.py        0      0   100%
app/config.py         15      0   100%
app/invoices.py       18      0   100%
app/people.py         24      0   100%
app/scheduler.py      21      0   100%
app/transfers.py      13      0   100%
app/webhook.py        30      0   100%
--------------------------------------
TOTAL                121      0   100%
```

Cada módulo tem seu próprio arquivo de teste. Todas as chamadas à API da
Stark Bank são mockadas — não são necessárias credenciais reais para rodar
os testes.

---

## Deploy (Docker / Cloud Run)

```bash
docker build -t starkbank-trial .

docker run -p 8080:8080 \
  -e STARKBANK_PROJECT_ID="..." \
  -e STARKBANK_PRIVATE_KEY="$(cat keys/privateKey.pem)" \
  -e STARKBANK_ENVIRONMENT="sandbox" \
  starkbank-trial
```

**Google Cloud Run (deploy direto):**

```bash
gcloud run deploy starkbank-trial \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars STARKBANK_PROJECT_ID="...",STARKBANK_ENVIRONMENT="sandbox"
# Armazene a PRIVATE_KEY no Secret Manager e injete via --set-secrets
```

---

## Variáveis de ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `STARKBANK_PROJECT_ID` | ID do Projeto criado no Sandbox | — |
| `STARKBANK_PRIVATE_KEY` | Chave privada ECDSA (PEM) | — |
| `STARKBANK_ENVIRONMENT` | `sandbox` ou `production` | `sandbox` |
| `PORT` | Porta do servidor Flask | `8080` |