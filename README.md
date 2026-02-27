# Stark Bank — Back-End Developer Trial

Integração Python com a API da Stark Bank que emite Invoices periodicamente, persiste seu ciclo de vida em banco de dados relacional e encaminha os pagamentos recebidos via Transfer — tudo com processamento assíncrono desacoplado por fila de eventos e um dashboard web em tempo real.

---

## Índice

1. [Stack](#1-stack)
2. [Arquitetura](#2-arquitetura)
   - [Visão geral dos módulos](#21-visão-geral-dos-módulos)
   - [Diagrama de componentes](#22-diagrama-de-componentes)
   - [Fluxo de dados completo](#23-fluxo-de-dados-completo)
   - [Modelo de dados](#24-modelo-de-dados)
3. [Processamento assíncrono — Queue Worker](#3-processamento-assíncrono--queue-worker)
4. [Modo Mock](#4-modo-mock)
5. [Dashboard Web](#5-dashboard-web)
6. [Setup e configuração](#6-setup-e-configuração)
   - [1. Pré-requisitos](#61-pré-requisitos)
   - [2. Gerar par de chaves ECDSA](#62-gerar-par-de-chaves-ecdsa)
   - [3. Configurar variáveis de ambiente](#63-configurar-variáveis-de-ambiente)
   - [4. Arquivos de configuração JSON](#64-arquivos-de-configuração-json)
   - [5. Instalar dependências](#65-instalar-dependências)
   - [6. Criar estrutura de diretórios](#66-criar-estrutura-de-diretórios)
   - [7. Registrar o webhook](#67-registrar-o-webhook)
   - [8. Executar](#68-executar)
7. [Testes](#7-testes)
8. [Modo Mock — execução local sem sandbox](#8-modo-mock--execução-local-sem-sandbox)
9. [Deploy em servidor Linux](#9-deploy-em-servidor-linux)
   - [Deploy via rsync + Systemd](#91-deploy-via-rsync--systemd)
   - [Configuração nginx + TLS](#92-configuração-nginx--tls)
10. [Deploy Docker / Cloud Run](#10-deploy-docker--cloud-run)
11. [Referência de variáveis de ambiente](#11-referência-de-variáveis-de-ambiente)
12. [Referência de endpoints](#12-referência-de-endpoints)
13. [Estrutura do projeto](#13-estrutura-do-projeto)

---

## 1. Stack

| Biblioteca | Versão | Papel |
|---|---|---|
| [`starkbank`](https://github.com/starkbank/sdk-python) | 2.20.0 | SDK principal — `invoice`, `transfer`, `webhook`, `event` |
| [`starkbank-ecdsa`](https://github.com/starkbank/ecdsa-python) | (dep. do SDK) | Geração de chaves secp256k1 e verificação de assinatura digital |
| [`starkcore`](https://github.com/starkbank/core-python) | (dep. do SDK) | Camada HTTP + autenticação interna do SDK |
| `Flask` | 3.0.3 | Servidor web — endpoint `/webhook`, `/health` e dashboard `/` |
| `APScheduler` | 3.10.4 | Scheduler em background thread — dispara lotes de invoices |
| `SQLAlchemy` | 2.0.47 | ORM — persistência do ciclo de vida das invoices em SQLite |
| `python-dotenv` | 1.2.1 | Carregamento do `.env` na inicialização |
| `psutil` | 7.2.2 | Telemetria de sistema no endpoint `/health` |
| `gunicorn` | 22.0.0 | Servidor WSGI para produção |
| `pytest` + `pytest-cov` | 8.2.2 / 5.0.0 | Testes unitários com cobertura |

---

## 2. Arquitetura

### 2.1 Visão geral dos módulos

```
app/
├── config.py           — Carregamento e validação de toda a configuração (env + JSON)
├── database.py         — ORM SQLAlchemy, init_db(), save_invoices(), mark_invoice_received()
├── invoices.py         — Geração e emissão de lote via starkbank.invoice.create()
├── transfers.py        — Repasse do valor líquido via starkbank.transfer.create()
├── people.py           — Gerador de pagadores fictícios com CPF matematicamente válido
├── scheduler.py        — APScheduler: dispara _job() imediatamente e a cada N horas por M horas
├── queue_worker.py     — Worker em daemon thread: consome fila, verifica ECDSA, despacha eventos
├── state.py            — Globals de memória (webhook_history, webhook_stats) e MockEvent/MockLog
├── webhook.py          — Flask app: POST /webhook, GET /health, GET / (dashboard)
└── mock_interceptor.py — Monkey-patch de requests.Session para redirecionar tráfego ao mock local
```

Arquivos raiz:

```
main.py                 — Entry point: orquestra init_db → mock_interceptor → init_starkbank → worker → scheduler → Flask
main_mock_starkbank.py  — Servidor Flask falso que simula a API da Stark Bank (porta 9090)
keygen.py               — Gera par de chaves ECDSA e salva em disco
setup_webhook.py        — Registra (ou verifica) o webhook na conta Stark Bank (executado 1x)
```

### 2.2 Diagrama de componentes

```
┌────────────────────────────────────────────────────────────────────┐
│                            main.py                                 │
│                                                                    │
│  ┌──────────────────┐   ┌─────────────────────────────────────┐   │
│  │    Scheduler      │   │         Flask App (webhook.py)      │   │
│  │  (BackgroundSched)│   │                                     │   │
│  │                  │   │   GET  /          → dashboard HTML   │   │
│  │  t=0:    _job() ─┼──►│   GET  /health   → JSON telemetria  │   │
│  │  t=3h:   _job() ─┼──►│   POST /webhook  → enfileira evento │   │
│  │  t=6h:   _job() ─┤   └────────────────┬────────────────────┘   │
│  │  ...             │                    │                         │
│  └──────────────────┘                    │ event_queue.put()       │
│                                          ▼                         │
│                              ┌───────────────────────┐            │
│                              │   queue_worker.py      │            │
│                              │   (daemon thread)      │            │
│                              │                        │            │
│                              │  starkbank.event.parse │            │
│                              │  (verifica ECDSA)      │            │
│                              └────────────┬───────────┘            │
│                                           │                        │
└───────────────────────────────────────────┼────────────────────────┘
                                            │
          ┌─────────────────────────────────┤
          │                                 │
          ▼                                 ▼
  ┌───────────────┐               ┌──────────────────┐
  │  invoices.py  │               │  transfers.py     │
  │               │               │                  │
  │  invoice      │               │  transfer        │
  │  .create()    │               │  .create()       │
  └───────┬───────┘               └────────┬─────────┘
          │                                │
          ▼                                ▼
  ┌───────────────┐               ┌──────────────────┐
  │  database.py  │               │  database.py     │
  │               │               │                  │
  │save_invoices()│               │mark_invoice_     │
  │  status:      │               │received()        │
  │  "enviado"    │               │  status:         │
  └───────────────┘               │  "recebido"      │
                                  └──────────────────┘
```

### 2.3 Fluxo de dados completo

```
 App                         Stark Bank API              Stark Bank Sandbox
  │                                │                              │
  │─── invoice.create([8..12]) ───►│                              │
  │◄── invoices criadas ───────────│                              │
  │─── save_invoices() [SQLite] ───┤                              │
  │    status="enviado"            │                              │
  │                                │                              │
  │    (a cada 3h até completar 24h, o ciclo acima se repete)     │
  │                                │                              │
  │                                │◄─── pagamento automático ────│
  │                                │     (Sandbox paga algumas    │
  │                                │      invoices aleatoriamente)│
  │                                │                              │
  │◄─── POST /webhook ─────────────│                              │
  │     Digital-Signature: <sig>   │                              │
  │     { subscription: "invoice", │                              │
  │       log.type: "credited",    │                              │
  │       invoice.amount: N,       │                              │
  │       invoice.fee:   F }       │                              │
  │                                │                              │
  │  event_queue.put(content, sig) │  ← retorna HTTP 200 imediato │
  │                                │                              │
  │  [worker thread]               │                              │
  │  starkbank.event.parse()       │                              │
  │  (verifica assinatura ECDSA)   │                              │
  │                                │                              │
  │─── transfer.create(N - F) ────►│                              │
  │    → conta Stark Bank S.A.     │                              │
  │                                │                              │
  │─── mark_invoice_received()     │                              │
  │    status="recebido"           │                              │
  │    transfer_id=<id>  [SQLite]  │                              │
```

### 2.4 Modelo de dados

Tabela `invoices` (SQLite via SQLAlchemy):

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | `TEXT` PK | ID da invoice na Stark Bank |
| `amount` | `INTEGER` | Valor em centavos |
| `name` | `TEXT` | Nome do pagador |
| `tax_id` | `TEXT` | CPF do pagador |
| `status` | `TEXT` | `"enviado"` → `"recebido"` |
| `created_at` | `TEXT` | ISO-8601 UTC — momento da emissão |
| `received_at` | `TEXT` nullable | ISO-8601 UTC — momento do webhook |
| `transfer_id` | `TEXT` nullable | ID da transfer gerada após o crédito |

O banco é inicializado por `init_db()` chamado em `main()` antes de qualquer outro subsistema. Se o arquivo `data/invoices.db` não existir, ele é criado automaticamente. O diretório `data/` deve existir antes da execução (veja [seção 6.6](#66-criar-estrutura-de-diretórios)).

---

## 3. Processamento assíncrono — Queue Worker

O webhook endpoint (`POST /webhook`) **nunca** bloqueia na verificação da assinatura ECDSA nem na execução da transfer. O payload é imediatamente enfileirado em um `queue.Queue` e o endpoint retorna `HTTP 200` para a Stark Bank.

Um daemon thread separado (`event-queue-worker`) consome a fila de forma contínua:

```
POST /webhook
     │
     │ content + signature + is_mock
     ▼
 event_queue (queue.Queue)
     │
     │ [daemon thread]
     ▼
 _process()
   ├─ is_mock=True  → valida ECDSA contra chave pública do mock server
   └─ is_mock=False → starkbank.event.parse() (busca chave pública da Stark Bank)
         │
         ▼
   _record_and_handle(event)
         │
         ├─ atualiza webhook_history (deque maxlen=50) e webhook_stats
         │
         └─ log.type == "credited"
               │
               ▼
         _dispatch_invoice(log)
               ├─ forward_payment(amount, fee) → starkbank.transfer.create()
               └─ mark_invoice_received(invoice_id, transfer_id) → SQLite
```

O histórico em memória (`webhook_history`, `webhook_stats` em `state.py`) é exibido no dashboard e sobrevive apenas à sessão do processo. O estado durável (ciclo de vida das invoices) está exclusivamente no SQLite.

---

## 4. Modo Mock

O modo mock permite executar o sistema completo **sem credenciais reais** e **sem acesso à internet**, usando um servidor Flask local que simula a API da Stark Bank.

**Componentes do modo mock:**

`main_mock_starkbank.py` — servidor na porta `9090` que implementa:
- `POST /v2/invoice` — finge criar invoices e agenda um webhook em 3 segundos
- `POST /v2/transfer` — finge criar transfers e loga no stdout
- `GET /v2/public-key` — retorna a chave pública mock para validação ECDSA

`mock_interceptor.py` — quando `USE_MOCK_API=true`, faz monkey-patch em `requests.Session.request` para redirecionar todo tráfego de `*.starkbank.com` para `http://127.0.0.1:9090`.

`state.py` — define `MockEvent`, `MockLog` e `MockInvoice` que replicam a interface dos objetos retornados pelo SDK real, permitindo que `queue_worker.py` processe eventos mock com o mesmo código de produção.

---

## 5. Dashboard Web

Acessível em `GET /` após iniciar a aplicação. Atualiza automaticamente a cada 15 segundos.

**Painel de métricas (dados do SQLite):**
- Invoices recebidas / total emitidas
- Volume financeiro processado (R$)
- Contagem de erros e rejeições

**Tabela de scheduler:** histórico das últimas 50 execuções do job com timestamp, status (`processing` / `success` / `error`), quantidade de invoices emitidas e IDs gerados.

**Tabela de webhook:** histórico dos últimos 50 eventos recebidos com horário, tipo (`invoice.credited`, etc.), ID da invoice e valor.

---

## 6. Setup e configuração

### 6.1 Pré-requisitos

- Python 3.11+
- Conta Stark Bank Sandbox criada em [sandbox.web.stark.com.br](https://sandbox.web.stark.com.br)
- URL pública com HTTPS para receber webhooks (ngrok, servidor próprio ou Cloud Run)

### 6.2 Gerar par de chaves ECDSA

```bash
python keygen.py keys/
```

Isso salva `keys/private-key.pem` e `keys/public-key.pem`. Faça upload do conteúdo de `public-key.pem` no painel:

```
Menu → Integrações → Novo Projeto → campo "Chave Pública"
```

Anote o **Project ID** gerado.

### 6.3 Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite `.env`:

```env
# Credenciais Stark Bank
STARKBANK_PROJECT_ID=seu_project_id_aqui
STARKBANK_PRIVATE_KEY=keys/private-key.pem
STARKBANK_PUBLIC_KEY=keys/public-key.pem
STARKBANK_ENVIRONMENT=sandbox

# Aplicação
APP_PORT=8080
LOG_LEVEL=INFO

# Banco de dados
DATABASE_URL=sqlite:///data/invoices.db

# Mock (desenvolvimento local sem sandbox)
USE_MOCK_API=false

# Caminhos dos arquivos de configuração JSON
STARTBANK_TRANSFER_CONFIG_PATH=config/transfer_destination.json
INVOICE_SCHEDULER_CONFIG_PATH=config/invoice_scheduler_config.json
```

> **Segurança:** `STARKBANK_PRIVATE_KEY` aponta para o **caminho** do arquivo PEM, não para o conteúdo. O arquivo é lido em runtime por `AppConfig`. Nunca comite o `.pem` ou o `.env` no repositório.

### 6.4 Arquivos de configuração JSON

**`config/transfer_destination.json`** — destino de todas as transfers:

```json
{
    "bank_code":      "20018183",
    "branch_code":    "0001",
    "account_number": "6341320293482496",
    "account_type":   "payment",
    "name":           "Stark Bank S.A.",
    "tax_id":         "20.018.183/0001-80"
}
```

**`config/invoice_scheduler_config.json`** — parametrização do scheduler:

```json
{
    "min_batch":       8,
    "max_batch":       12,
    "interval_hours":  3,
    "duration_hours":  24
}
```

| Campo | Descrição |
|---|---|
| `min_batch` | Número mínimo de invoices por lote |
| `max_batch` | Número máximo de invoices por lote |
| `interval_hours` | Intervalo entre lotes (horas) |
| `duration_hours` | Duração total do ciclo de emissão (horas) |

Com a configuração padrão: lotes de 8–12 invoices, emitidos a cada 3 horas, durante 24 horas — totalizando 9 disparos (t=0, t=3h, t=6h, ..., t=24h) e entre 72 e 108 invoices.

### 6.5 Instalar dependências

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 6.6 Criar estrutura de diretórios

```bash
mkdir -p data config keys
```

O SQLite precisa que o diretório `data/` exista antes do primeiro `init_db()`. Os arquivos JSON vão em `config/` e os PEMs em `keys/`.

### 6.7 Registrar o webhook

Execute este script **uma única vez** após o deploy (ou com ngrok ativo localmente):

```bash
# Com ngrok:
ngrok http 8080
python setup_webhook.py https://abc123.ngrok.io/webhook

# Com URL de produção:
python setup_webhook.py https://seu-dominio.com/webhook
```

O script verifica se o webhook já está registrado antes de criar um novo. Para listar todos os webhooks ativos:

```bash
python setup_webhook.py https://qualquer-url.com/webhook
# Ao final, lista todos os webhooks registrados na conta
```

### 6.8 Executar

```bash
python main.py
```

Sequência de inicialização:

1. `AppConfig` carrega e valida todas as variáveis e arquivos de configuração
2. `mock_interceptor` é ativado se `USE_MOCK_API=true`
3. `init_db()` cria a tabela `invoices` se não existir
4. `config.init_starkbank()` autentica o SDK com o `starkbank.Project`
5. `start_worker()` inicia o daemon thread de processamento de eventos
6. `start_scheduler()` registra e inicia os jobs de emissão de invoices
7. Flask sobe na porta configurada (`APP_PORT`, padrão `8080`)

O primeiro lote de invoices é disparado imediatamente no startup, seguido de lotes periódicos conforme `invoice_scheduler_config.json`.

---

## 7. Testes

```bash
pytest
```

Todos os módulos em `app/` têm cobertura de 100%. As chamadas à API da Stark Bank são mockadas — nenhuma credencial real é necessária para rodar os testes.

```
Name                    Stmts   Miss  Cover
-------------------------------------------
app/__init__.py             0      0   100%
app/config.py              XX      0   100%
app/database.py            XX      0   100%
app/invoices.py            XX      0   100%
app/mock_interceptor.py    XX      0   100%
app/people.py              XX      0   100%
app/queue_worker.py        XX      0   100%
app/scheduler.py           XX      0   100%
app/state.py               XX      0   100%
app/transfers.py           XX      0   100%
app/webhook.py             XX      0   100%
-------------------------------------------
TOTAL                     XXX      0   100%
```

Para rodar com relatório de cobertura HTML:

```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

---

## 8. Modo Mock — execução local sem sandbox

Para desenvolver e testar sem depender do ambiente sandbox da Stark Bank:

**Terminal 1 — servidor mock da Stark Bank:**

```bash
# Coloque suas credenciais reais no .env mesmo em modo mock
# O mock server usa a chave privada configurada para assinar os webhooks
python main_mock_starkbank.py
# 🏦 STARK BANK MOCK SERVER INICIADO NA PORTA 9090
```

**Terminal 2 — aplicação com mock ativado:**

```bash
USE_MOCK_API=true python main.py
# ou configure USE_MOCK_API=true no .env
```

**O que acontece:**

1. `mock_interceptor` redireciona `starkbank.invoice.create()` para `http://127.0.0.1:9090/v2/invoice`
2. O mock server registra as invoices e agenda um webhook em ~3 segundos
3. O webhook é enviado com assinatura ECDSA usando o par de chaves mock (gerado em memória)
4. O `queue_worker` detecta `is_mock=True`, busca a chave pública em `GET /v2/public-key` e valida a assinatura
5. `forward_payment()` é chamado e a transfer vai para `POST /v2/transfer` no mock
6. O mock loga a transfer no stdout: `💰 TRANSFERÊNCIA RECEBIDA! Valor: X para Stark Bank S.A.`

O fluxo completo — emissão, pagamento, webhook, validação ECDSA, transfer — ocorre sem nenhuma chamada externa.

---

## 9. Deploy em servidor Linux

### 9.1 Deploy via rsync + Systemd

```bash
bash deploy.sh
```

O script executa:

1. Instala `rsync` no servidor remoto (se necessário)
2. Sincroniza os arquivos do projeto via rsync (excluindo `.venv`, `.git`, chaves SSH)
3. Cria o virtualenv e instala dependências
4. Cria e habilita o serviço `starkbank.service` no Systemd
5. Reinicia o serviço e exibe o status

O serviço Systemd é configurado com `Restart=always` e `RestartSec=5`. Para acompanhar os logs em produção:

```bash
sudo journalctl -u starkbank -f
```

**Pré-requisito:** configure as variáveis no `.env` local antes de rodar o deploy. O `.env` é sincronizado via rsync com permissões `600`.

### 9.2 Configuração nginx + TLS

Após a propagação DNS do subdomínio para o IP do servidor:

```bash
bash setup_server.sh
```

O script:

1. Verifica a propagação DNS via `dig`
2. Instala nginx e certbot no servidor remoto
3. Configura o nginx como reverse proxy para a porta `APP_PORT`
4. Emite certificado SSL via Let's Encrypt (certbot + nginx plugin)
5. Configura renovação automática via `certbot.timer`

Após a execução:

```
Webhook URL:  https://seu-dominio.com/webhook
Dashboard:    https://seu-dominio.com/
Health:       https://seu-dominio.com/health
```

---

## 10. Deploy Docker / Cloud Run

**Build e execução local:**

```bash
docker build -t starkbank-trial .

docker run -p 8080:8080 \
  -e STARKBANK_PROJECT_ID="seu_project_id" \
  -e STARKBANK_PRIVATE_KEY="/run/secrets/private_key" \
  -e STARKBANK_PUBLIC_KEY="/run/secrets/public_key" \
  -e STARKBANK_ENVIRONMENT="sandbox" \
  -v /path/to/keys:/run/secrets:ro \
  starkbank-trial
```

**Google Cloud Run:**

```bash
gcloud run deploy starkbank-trial \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars STARKBANK_PROJECT_ID="...",STARKBANK_ENVIRONMENT="sandbox"
```

> Para as chaves PEM no Cloud Run, use o Secret Manager:
>
> ```bash
> gcloud secrets create starkbank-private-key --data-file=keys/private-key.pem
> gcloud secrets create starkbank-public-key  --data-file=keys/public-key.pem
> # Injete via --set-secrets no deploy
> ```

---

## 11. Referência de variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `STARKBANK_PROJECT_ID` | ✅ | — | ID do Projeto criado no painel Stark Bank |
| `STARKBANK_PRIVATE_KEY` | ✅ | — | **Caminho** para o arquivo `private-key.pem` |
| `STARKBANK_PUBLIC_KEY` | ✅ | — | **Caminho** para o arquivo `public-key.pem` |
| `STARKBANK_ENVIRONMENT` | — | `sandbox` | `sandbox` ou `production` |
| `APP_PORT` | — | `8080` | Porta do servidor Flask |
| `LOG_LEVEL` | — | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DATABASE_URL` | — | `sqlite:///data/invoices.db` | URL de conexão SQLAlchemy |
| `USE_MOCK_API` | — | `false` | `true` para ativar o mock interceptor |
| `STARTBANK_TRANSFER_CONFIG_PATH` | — | `config/transfer_destination.json` | Caminho para o JSON de destino de transfer |
| `INVOICE_SCHEDULER_CONFIG_PATH` | — | `config/invoice_scheduler_config.json` | Caminho para o JSON do scheduler |

---

## 12. Referência de endpoints

### `POST /webhook`

Recebe callbacks da Stark Bank. O payload e a assinatura são enfileirados para processamento assíncrono.

**Headers esperados:**
- `Content-Type: application/json`
- `Digital-Signature: <assinatura ECDSA em Base64>`

**Respostas:**
- `200 {"status": "queued"}` — evento enfileirado com sucesso
- `400 {"error": "empty body"}` — body vazio

### `GET /health`

Retorna status e telemetria do processo.

```json
{
  "status": "ok",
  "timestamp": "2025-01-15T14:32:00Z",
  "service": "starkbank-webhook-manager",
  "telemetry": {
    "uptime_seconds": 3600,
    "cpu": { "usage_percent": 2.1, "cores": 2 },
    "memory": { "total_mb": 1024, "available_mb": 820, "used_percent": 19.9 },
    "disk": { "free_gb": 18.5, "used_percent": 12.3 }
  }
}
```

O campo `status` assume `"warning"` quando `cpu_usage > 95%` ou `memory.percent > 95%`.

### `GET /`

Dashboard HTML com auto-refresh a cada 15 segundos. Exibe métricas do SQLite, histórico do scheduler e histórico de webhooks.

---

## 13. Estrutura do projeto

```
starkbank-trial/
│
├── app/                            ← pacote principal
│   ├── __init__.py
│   ├── config.py                   ← AppConfig: carrega .env, valida, lê JSONs e PEMs
│   ├── database.py                 ← SQLAlchemy engine, InvoiceRecord, init_db(), save/mark/stats
│   ├── invoices.py                 ← issue_batch(): gera e emite lote, persiste no banco
│   ├── transfers.py                ← forward_payment(): calcula valor líquido e cria transfer
│   ├── people.py                   ← random_payer() com CPF válido, telefone e e-mail fictícios
│   ├── scheduler.py                ← start_scheduler(): APScheduler + job_history (deque)
│   ├── queue_worker.py             ← event_queue, _process(), _dispatch_invoice(), start_worker()
│   ├── state.py                    ← webhook_history, webhook_stats, MockEvent/MockLog/MockInvoice
│   ├── webhook.py                  ← Flask: /webhook, /health, / (dashboard)
│   └── mock_interceptor.py         ← setup_mock_interceptor(): redireciona tráfego starkbank.com
│
├── tests/                          ← cobertura 100%
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_invoices.py
│   ├── test_transfers.py
│   ├── test_people.py
│   ├── test_scheduler.py
│   ├── test_queue_worker.py
│   ├── test_state.py
│   ├── test_webhook.py
│   └── test_mock_interceptor.py
│
├── config/                         ← arquivos de configuração JSON
│   ├── transfer_destination.json
│   └── invoice_scheduler_config.json
│
├── keys/                           ← chaves ECDSA (não versionar)
│   ├── private-key.pem             ← .gitignore este arquivo
│   └── public-key.pem
│
├── data/                           ← banco de dados SQLite (não versionar)
│   └── invoices.db
│
├── main.py                         ← entry point
├── main_mock_starkbank.py          ← servidor mock da API Stark Bank (porta 9090)
├── keygen.py                       ← geração de par de chaves ECDSA
├── setup_webhook.py                ← registro do webhook na conta Stark Bank (executar 1x)
├── deploy.sh                       ← deploy via rsync + Systemd
├── setup_server.sh                 ← configuração nginx + TLS (Let's Encrypt)
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── .env.example
└── .gitignore                      ← deve incluir: .env, keys/, data/
```