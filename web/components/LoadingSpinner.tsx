export default function LoadingSpinner({ text = 'Memuat data...' }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
      <div className="relative w-12 h-12">
        <div className="absolute inset-0 rounded-full border-2 border-slate-700" />
        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-sky-400 animate-spin" />
      </div>
      <p className="text-sm text-slate-400">{text}</p>
    </div>
  )
}

export function InlineLoader() {
  return (
    <div className="flex items-center justify-center py-8">
      <div className="w-6 h-6 rounded-full border-2 border-slate-600 border-t-sky-400 animate-spin" />
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 px-6 text-center">
      <p className="text-4xl">❌</p>
      <p className="text-slate-200 font-semibold">Gagal memuat data</p>
      <p className="text-sm text-slate-400 leading-relaxed">{error.message}</p>
      <button
        onClick={onRetry}
        className="mt-2 px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white rounded-xl text-sm font-semibold transition-colors touch-action"
      >
        Coba Lagi
      </button>
    </div>
  )
}
