"""Glosarium istilah trading — Bahasa Indonesia, untuk awam."""
from __future__ import annotations

GLOSSARY = [
    # Basic
    ("XAU/USD", "Pair gold (emas) terhadap USD. Harga emas dalam dollar per troy ounce. 1 lot standar = 100 oz."),
    ("Pip", "Pergerakan harga terkecil. Untuk XAU/USD: 1 pip = $0.01. Jadi dari $2000.00 ke $2000.50 = 50 pips."),
    ("Lot", "Ukuran posisi. Standard lot = 100 oz, mini lot (0.1) = 10 oz, micro lot (0.01) = 1 oz."),
    ("Spread", "Selisih harga beli (ask) dan harga jual (bid). XAU spread typical 20-30 cents."),
    ("Leverage", "Berapa kali modal kita yang dipakai broker. 1:100 leverage = $1000 modal bisa control posisi $100K."),
    ("Margin", "Jaminan yang ditahan broker untuk maintain posisi terbuka. Habis margin = liquidation."),

    # Order types
    ("Entry", "Harga di mana kita masuk posisi (buy/sell)."),
    ("SL (Stop Loss)", "Harga otomatis exit untuk batasi rugi. WAJIB pakai biar nggak account habis."),
    ("TP (Take Profit)", "Harga otomatis exit untuk ambil profit. TP1/TP2/TP3 = bertahap."),
    ("R:R (Risk:Reward)", "Rasio rugi-untung. R:R 2.0 = potensi profit 2x dari risk. Minimal 1.5 idealnya."),
    ("R-multiple", "Profit/loss diukur kelipatan risk. Win = +2R artinya untung 2x dari yang dipertaruhkan."),

    # Strategy styles
    ("Scalper", "Trade dalam menit. Buka-tutup cepat. Frekuensi tinggi, profit kecil per trade. Stress tinggi."),
    ("Intraday", "Trade dibuka dan ditutup di hari yang sama. Hold 1-8 jam. Balance frekuensi dan effort."),
    ("Swing", "Hold 2-7 hari. Frekuensi rendah, profit besar per trade kalau benar. Cocok part-time trader."),

    # Technical indicators
    ("EMA (Exponential Moving Average)", "Rata-rata harga yang lebih sensitif ke harga terbaru. EMA9, EMA21, EMA50, EMA200 = filter trend."),
    ("RSI (Relative Strength Index)", "Indikator momentum 0-100. >70 overbought (mau turun?), <30 oversold (mau naik?)."),
    ("MACD", "Indikator momentum berdasar selisih EMA. Histogram positif = momentum naik, negatif = turun."),
    ("ATR (Average True Range)", "Indikator volatility. Dipakai buat hitung jarak SL/TP yang masuk akal."),
    ("ADX (Average Directional Index)", "Kekuatan trend 0-100. >25 = trending, <20 = ranging/sideways."),
    ("Bollinger Bands", "Channel di atas/bawah harga rata-rata. Harga di band atas = overbought-ish."),

    # SMC / institutional concepts
    ("SMC (Smart Money Concepts)", "Konsep ICT — baca jejak institusional di chart."),
    ("Liquidity Sweep / Stop Hunt", "Harga 'menusuk' di atas swing high atau bawah swing low buat trigger stop loss retail, lalu balik arah."),
    ("FVG (Fair Value Gap)", "Gap antara high candle 1 dan low candle 3. Sering di-retest sebelum lanjut. Indikator institutional flow."),
    ("Order Block", "Candle terakhir yang berlawanan sebelum impulsive move. Area S/R kuat."),
    ("BOS (Break of Structure)", "Harga break swing high/low sebelumnya. Konfirmasi continuation trend."),

    # Macro / fundamental
    ("DXY (Dollar Index)", "Indeks USD vs basket currency utama. DXY naik = USD kuat = XAU biasanya turun."),
    ("US 10Y Yield", "Bunga obligasi pemerintah US 10 tahun. Yield naik = bond menarik = USD menarik = XAU turun."),
    ("Real Yield (TIPS)", "Yield setelah dikurangi inflasi. Driver #1 XAU. Korelasi -0.85+."),
    ("VIX", "'Fear index'. VIX spike = pasar takut = XAU sering naik (safe haven)."),
    ("COT Report", "Laporan posisi trader besar (CFTC). Extreme net long/short = sinyal mean reversion."),

    # News / risk
    ("News Blackout", "Periode 30 menit sebelum/sesudah event high-impact (FOMC, NFP, CPI). Engine auto-veto entry — terlalu acak."),
    ("NFP (Non-Farm Payrolls)", "Data lapangan kerja US, rilis Jumat pertama tiap bulan. High impact ke USD & XAU."),
    ("FOMC", "Pertemuan Federal Reserve. Keputusan suku bunga. Volatility tinggi setelah rilis."),
    ("CPI (Consumer Price Index)", "Data inflasi US. Inflasi tinggi = Fed hawkish = USD kuat = XAU turun (biasanya)."),

    # Risk management
    ("Risk per trade", "% modal yang siap rugi per posisi. Standard: 1-2%. Konservatif: 0.5%."),
    ("Drawdown (DD)", "Penurunan equity dari peak. Max DD = penurunan terbesar yang pernah terjadi."),
    ("Kelly Criterion", "Formula matematis ukuran posisi optimal berdasar win rate dan R:R. Kita pake 0.25× Kelly (institutional safe)."),
    ("Sharpe Ratio", "Return per unit risk. >1 = bagus, >2 = sangat bagus, >3 = excellent."),
    ("Win Rate", "% trade yang profit. NB: 50% win rate dengan R:R 2.0 sudah profitable jangka panjang."),
    ("Expectancy", "Average profit per trade dalam R-multiples. Positif = strategi punya edge."),

    # Engine / AI
    ("Confluence", "Jumlah faktor yang agree dalam satu arah. Makin banyak makin tinggi confidence."),
    ("Multi-Agent Debate", "4 AI agent (Tech/Macro/OrderFlow/DevilsAdvocate) debat → 3 dari 4 harus agree baru fire signal."),
    ("Confidence", "Probabilitas (0-100%) signal valid menurut engine. >65% = valid, >80% = STRONG."),
    ("Signal Strength", "Kategori: STRONG (4-of-4 agree, conf >80%), NORMAL (3-of-4, conf >65%), WEAK (conf >50%), FLAT (no consensus)."),
    ("Monte Carlo", "Simulasi 100k path alternatif dari hasil backtest. Ngelihat seberapa robust strategi vs sekedar lucky."),
    ("Walk-forward", "Validation method: train pake data lama, test pake data baru. Hindari overfitting."),
]


def search(query: str) -> list[tuple[str, str]]:
    q = query.lower().strip()
    if not q:
        return GLOSSARY
    return [(t, d) for t, d in GLOSSARY if q in t.lower() or q in d.lower()]
