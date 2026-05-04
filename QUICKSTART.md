# yeehee — Quickstart

Personal XAU/USD signal platform. **Combo A+B**: Streamlit dashboard di laptop + Telegram bot push ke HP.

---

## Step 1: Install Python

Download Python 3.11+ dari https://www.python.org/downloads/ → install dengan **"Add Python to PATH"** centang.

```cmd
python --version
```

## Step 2: Setup (auto)

Double-click `setup.bat`. Bakal:
- Bikin venv di `.venv\`
- Install dependencies (~3-5 menit, ~600 MB)
- Copy `.env.example` → `.env`

Atau manual:
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Step 3: Smoke test

```cmd
run.bat test
```

Harusnya `RESULT: 18+ passed, 0 failed` (~10-30 detik karena fetch data pertama kali).

## Step 4: Run dashboard di laptop

```cmd
run.bat
```

Browser auto-buka di http://localhost:8501. **7 tab interactive:**
- 🎯 Live Signals (3 styles)
- 📈 Chart & Levels (Plotly candlestick + EMA + BB + SMC marks)
- 🧠 Multi-Agent Debate
- 💰 Risk Calculator (4 profile: konservatif/moderat/agresif/bebas + Kelly)
- 📅 News Calendar (high-impact 7 hari)
- 🔬 Backtest + Monte Carlo 100k
- ℹ️ About

---

## Step 5: Setup Telegram bot (~5 menit)

### 5a. Bikin bot via BotFather
1. Buka Telegram, search **@BotFather**
2. Kirim `/newbot`
3. Kasih nama (e.g. "yeehee_signal")
4. Kasih username (harus akhiran `_bot`, e.g. `yeehee_signal_bot`)
5. Copy **token** yang dikasih

### 5b. Cari chat ID lo
1. Buka bot baru lo, kirim `/start` (bot belum aktif tapi tetep kirim aja)
2. Search **@userinfobot**, kirim `/start` ke dia
3. Copy **ID** yang dikasih

### 5c. Edit `.env`
```env
TELEGRAM_BOT_TOKEN=123456:ABCdef...
TELEGRAM_CHAT_ID=12345678
```

Mau invite **orang terdekat**? Pisahkan koma:
```env
TELEGRAM_CHAT_ID=12345678,87654321,11223344
```

### 5d. Run bot
```cmd
run.bat bot
```

Lo akan dapet pesan welcome di Telegram. Coba command:
- `/signal` — semua signal lengkap
- `/signal scalper` — scalper only
- `/risk 5000 LONG 2030 2025 2040` — lot calc semua profile
- `/news` — events 48 jam ke depan
- `/regime` — regime saat ini
- `/debate` — full 4-agent debate
- `/strong on|off` — toggle auto-push STRONG signal

**Auto-push**: setiap 10 menit bot cek signal. Kalau strength = STRONG / NEWS_STRONG dan beda dari yang sebelumnya, lo dapat alert duarr di HP.

---

## Step 6 (opsional): Akses dashboard dari HP

Pake Cloudflare Tunnel (gratis, no signup, no bandwidth limit):

### Install cloudflared
```cmd
winget install --id Cloudflare.cloudflared
```
Atau download manual dari https://github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.exe)

### Jalanin tunnel
Setelah dashboard jalan (`run.bat`), buka cmd kedua:
```cmd
cloudflared tunnel --url http://localhost:8501
```

Akan keluar URL kayak `https://random-words-xyz.trycloudflare.com` — buka di HP. Done.

⚠️ URL berubah tiap restart tunnel. Buat URL permanen butuh setup Cloudflare account (tetap gratis), tapi quick-tunnel ini cukup buat occasional access.

---

## Daily workflow

**Pagi (laptop):**
- `run.bat` → buka dashboard, cek regime + upcoming news
- Lihat signal STRONG → catat level entry/SL/TP

**Siang (HP):**
- Bot push notif kalau ada signal STRONG baru → review cepet → eksekusi di broker app
- `/news` cek event impactful malam ini

**Sore/malam (laptop):**
- Backtest ulang strategi kalau perlu
- Lihat equity curve dari posisi yg kebuka

**Background (24/5):**
- Bot lo running di laptop yang ON, push ke HP terus

---

## Troubleshooting

**Bot offline saat dipanggil** — laptop harus ON dengan `run.bat bot` terus jalan. Buat persistent: pake Task Scheduler / service. Atau jalanin di mini-PC / Raspberry Pi 24/7.

**Cloudflare tunnel timeout** — quick-tunnel kadang timeout di session lama. Restart tunnel.

**`generate_signals` lambat (>30 detik)** — yfinance throttle. Hapus `data_cache\` buat reset, atau tunggu beberapa menit.

**Signal STRONG nggak pernah keluar** — karena threshold ketat (4-of-4 agent agree + conf >0.80). Itu by design — STRONG = high quality only. Mayoritas sinyal harian akan NORMAL atau WEAK. Cek dashboard tab "Multi-Agent Debate" buat lihat kenapa.

**`pandas-ta` error saat install** — gua nggak pake pandas-ta di kode. Edit `requirements.txt` hapus baris itu, re-install.

**ImportError saat `streamlit run`** — pastikan `.venv\Scripts\activate` aktif.

---

## Realistic expectations

- Win rate target: 55–65% (institutional standard)
- R:R 1.5–2.5
- STRONG signal: 1-3× per minggu (kondisi konfluensi tinggi langka)
- NORMAL signal: lebih sering, tapi bukan auto-execute — review dulu
- Max DD target <15%
- **Past performance ≠ future result.** Tools ini bantu lo decide, bukan auto-trader.
