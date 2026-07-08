# Deploy do RENDE IA em VPS (Hostinger KVM) — Guia rápido

Passo a passo para subir o sistema em produção com `https://rende-ia.com.br`.
Plano recomendado: **KVM 2 (8 GB / 2 vCPU)**. O KVM 1 (4 GB / 1 vCPU) roda sem
OOM em cenário de baixo tráfego, mas com margem de CPU apertada durante o scraping.

---

## 0. Alterações de código já aplicadas neste repositório

- `client/script.js` → `API_URL = ""` (chamada relativa, mesma origem, herda HTTPS).
- `app.py` → CORS restrito a `rende-ia.com.br` (sobrescrevível por `RENDE_IA_CORS_ORIGINS`).
- `docker-compose.yml` → porta publicada só em `127.0.0.1:8000`, rotação de logs
  (`max-size: 10m`, `max-file: 5`), `restart: unless-stopped` mantido.

> Mantenha **1 worker** Uvicorn (padrão do Dockerfile). O dedupe (`_analises_em_andamento`),
> o cache de IPCA (`_IPCA_CACHE`) e o scheduler (`_db_scheduler`) vivem em memória —
> `--workers N` quebraria o dedupe e faria o job das 02:00 disparar N vezes.

---

## 1. Preparar a VPS

```bash
# Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
sudo apt-get install -y docker-compose-plugin nginx certbot python3-certbot-nginx

# (Opcional) limitar logs de TODOS os containers globalmente
# /etc/docker/daemon.json:
# { "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }
# sudo systemctl restart docker
```

## 2. Firewall (UFW)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp      # SSH — idealmente restrinja ao seu IP: ufw allow from SEU_IP to any port 22
sudo ufw allow 80/tcp      # HTTP (redirect → HTTPS)
sudo ufw allow 443/tcp     # HTTPS
sudo ufw enable
```

A porta 8000 **não** é aberta. A publicação em `127.0.0.1:8000` no compose já
impede acesso externo direto ao container (defesa independente do UFW, que o
Docker às vezes contorna via iptables).

## 3. Subir a aplicação

```bash
cd IA_INVESTE
nano .env                 # GEMINI_API_KEY, GEMINI_MODEL, RENDE_IA_GEMINI_MODE=real, etc.
chmod 600 .env            # segredo legível só pelo dono
docker compose up -d --build
docker compose ps         # aguarde status (healthy)
```

> ⚠️ Confirme `GEMINI_MODEL` no `.env`. O valor atual (`gemini-3.1-flash-lite`)
> aparenta ser um id inválido — em modo `real` isso derruba toda análise para o
> fallback determinístico. Ajuste para um modelo Gemini válido antes do go-live.

## 4. Nginx + SSL

```bash
sudo cp deploy/nginx-rende-ia.conf /etc/nginx/sites-available/rende-ia
sudo ln -s /etc/nginx/sites-available/rende-ia /etc/nginx/sites-enabled/rende-ia
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# Emite o certificado e injeta a config SSL automaticamente:
sudo certbot --nginx -d rende-ia.com.br -d www.rende-ia.com.br
```

Aponte o DNS de `rende-ia.com.br` (registro A) e `www` para o IP da VPS **antes**
de rodar o certbot. A renovação é automática (systemd timer do certbot).

## 5. Validação

```bash
curl -I https://rende-ia.com.br/                 # 200 + HTTPS
curl    https://rende-ia.com.br/api/health       # {"status":"online",...}
docker compose logs -f rende-ia                  # scheduler + Gemini
```

## 6. Atualização do banco (scraping)

Roda sozinho todo dia às 02:00 (America/Belem). Para forçar manualmente:

```bash
docker exec -e DISPLAY=:99 rende-ia python banco_dados.py
```

## 7. Operação

```bash
docker compose logs -f rende-ia     # acompanhar
docker compose restart rende-ia     # reiniciar
docker compose down                 # parar (mantém o volume/SQLite)
docker compose up -d --build        # atualizar após git pull
```
