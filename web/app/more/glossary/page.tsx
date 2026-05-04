'use client'
import { useState } from 'react'
import { Search } from 'lucide-react'

const GLOSSARY: [string, string][] = [
  ['XAU/USD', 'Pair gold (emas) terhadap USD. Harga emas dalam dollar per troy ounce. 1 lot standar = 100 oz.'],
  ['Pip', 'Pergerakan harga terkecil. Untuk XAU/USD: 1 pip = $0.01. Dari $2000.00 ke $2000.50 = 50 pips.'],
  ['Lot', 'Ukuran posisi. Standard lot = 100 oz, mini lot (0.1) = 10 oz, micro lot (0.01) = 1 oz.'],
  ['Spread', 'Selisih harga beli (ask) dan harga jual (bid). XAU spread typical 20-30 cents.'],
  ['Leverage', 'Berapa kali modal yang dipakai broker. 1:100 = $1000 modal bisa kontrol posisi $100K.'],
  ['Margin', 'Jaminan yang ditahan broker untuk posisi terbuka. Habis margin = liquidation.'],
  ['Entry', 'Harga di mana kita masuk posisi (buy/sell).'],
  ['SL (Stop Loss)', 'Harga otomatis exit untuk batasi rugi. WAJIB pakai biar nggak account habis.'],
  ['TP (Take Profit)', 'Harga otomatis exit untuk ambil profit. TP1/TP2/TP3 = bertahap.'],
  ['R:R (Risk:Reward)', 'Rasio rugi-untung. R:R 2.0 = potensi profit 2x dari risk. Minimal 1.5 idealnya.'],
  ['R-multiple', 'Profit/loss diukur kelipatan risk. +2R artinya untung 2x dari yang dipertaruhkan.'],
  ['Scalper', 'Trade dalam menit. Buka-tutup cepat. Frekuensi tinggi, profit kecil per trade.'],
  ['Intraday', 'Trade dibuka dan ditutup di hari yang sama. Hold 1-8 jam.'],
  ['Swing', 'Hold 2-7 hari. Frekuensi rendah, profit besar per trade kalau benar. Cocok part-time trader.'],
  ['EMA', 'Exponential Moving Average. Rata-rata harga yang lebih sensitif ke harga terbaru. EMA9/21/50/200.'],
  ['RSI', 'Relative Strength Index. Indikator momentum 0-100. >70 overbought, <30 oversold.'],
  ['MACD', 'Indikator momentum berdasar selisih EMA. Histogram positif = momentum naik.'],
  ['ATR', 'Average True Range. Indikator volatility. Dipakai buat hitung jarak SL/TP.'],
  ['ADX', 'Average Directional Index. Kekuatan trend 0-100. >25 = trending, <20 = ranging.'],
  ['Bollinger Bands', 'Channel di atas/bawah harga rata-rata. Harga di band atas = overbought-ish.'],
  ['SMC', 'Smart Money Concepts — konsep ICT, baca jejak institusional di chart.'],
  ['Liquidity Sweep', 'Harga "menusuk" swing high/low buat trigger stop loss retail, lalu balik arah.'],
  ['FVG', 'Fair Value Gap — gap antara high candle 1 dan low candle 3. Sering di-retest.'],
  ['Order Block', 'Candle terakhir berlawanan sebelum impulsive move. Area S/R kuat.'],
  ['BOS', 'Break of Structure — harga break swing high/low sebelumnya. Konfirmasi trend.'],
  ['DXY', 'Dollar Index. DXY naik = USD kuat = XAU biasanya turun. Korelasi negatif kuat.'],
  ['US 10Y Yield', 'Bunga obligasi US 10 tahun. Yield naik = USD menarik = XAU turun.'],
  ['Real Yield (TIPS)', 'Yield setelah dikurangi inflasi. Driver #1 XAU. Korelasi -0.85+.'],
  ['VIX', '"Fear index". VIX spike = pasar takut = XAU sering naik (safe haven).'],
  ['COT Report', 'Laporan posisi trader besar (CFTC). Extreme net long/short = sinyal mean reversion.'],
  ['News Blackout', 'Periode 30 mnt sebelum/sesudah event high-impact. Engine auto-veto entry.'],
  ['NFP', 'Non-Farm Payrolls. Data lapangan kerja US, rilis Jumat pertama tiap bulan.'],
  ['FOMC', 'Pertemuan Federal Reserve. Keputusan suku bunga. Volatility tinggi setelah rilis.'],
  ['CPI', 'Consumer Price Index. Data inflasi US. Inflasi tinggi = Fed hawkish = USD kuat = XAU turun.'],
  ['Risk per trade', '% modal yang siap rugi per posisi. Standard: 1-2%. Konservatif: 0.5%.'],
  ['Drawdown (DD)', 'Penurunan equity dari peak. Max DD = penurunan terbesar yang pernah terjadi.'],
  ['Kelly Criterion', 'Formula matematis ukuran posisi optimal. Kita pakai 0.25× Kelly (institutional safe).'],
  ['Sharpe Ratio', 'Return per unit risk. >1 = bagus, >2 = sangat bagus, >3 = excellent.'],
  ['Win Rate', '% trade yang profit. 50% win rate dengan R:R 2.0 sudah profitable jangka panjang.'],
  ['Expectancy', 'Average profit per trade dalam R-multiples. Positif = strategi punya edge.'],
  ['Confluence', 'Jumlah faktor yang agree dalam satu arah. Makin banyak makin tinggi confidence.'],
  ['Multi-Agent Debate', '4 AI agent debat → 3 dari 4 harus agree baru fire signal.'],
  ['Confidence', 'Probabilitas (0-100%) signal valid menurut engine. >65% = valid, >80% = STRONG.'],
  ['Signal Strength', 'Kategori: STRONG (4-of-4, conf >80%), NORMAL (3-of-4, conf >65%), WEAK, FLAT.'],
  ['Monte Carlo', 'Simulasi ribuan path alternatif dari backtest. Lihat robustness vs sekedar luck.'],
  ['Walk-forward', 'Validation method: train pakai data lama, test pakai data baru. Hindari overfitting.'],
]

export default function GlossaryPage() {
  const [query, setQuery] = useState('')

  const results = query
    ? GLOSSARY.filter(([t, d]) =>
        t.toLowerCase().includes(query.toLowerCase()) ||
        d.toLowerCase().includes(query.toLowerCase()),
      )
    : GLOSSARY

  return (
    <main className="max-w-lg mx-auto px-4 pt-4 pb-2 space-y-3 animate-fade-in">
      <div>
        <h1 className="text-lg font-black text-slate-100">📖 Glosarium Trading</h1>
        <p className="text-xs text-slate-500 mt-0.5">{GLOSSARY.length} istilah dalam Bahasa Indonesia</p>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Cari istilah (RSI, lot, FVG...)"
          className="w-full bg-slate-800/60 border border-slate-700/50 rounded-2xl pl-9 pr-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-sky-500"
        />
      </div>

      {results.length === 0 && (
        <p className="text-center text-slate-500 py-8">Tidak ditemukan.</p>
      )}

      <div className="space-y-2">
        {results.map(([term, def]) => (
          <details
            key={term}
            className="bg-slate-800/60 rounded-2xl border border-slate-700/40 group"
          >
            <summary className="flex items-center justify-between px-4 py-3 cursor-pointer select-none list-none">
              <span className="font-semibold text-sm text-slate-100">{term}</span>
              <span className="text-slate-500 text-lg group-open:rotate-45 transition-transform">+</span>
            </summary>
            <p className="px-4 pb-3 text-xs text-slate-400 leading-relaxed border-t border-slate-700/40 pt-2">
              {def}
            </p>
          </details>
        ))}
      </div>

      <p className="text-center text-[10px] text-slate-600">
        {results.length} dari {GLOSSARY.length} istilah ditampilkan
      </p>
    </main>
  )
}
