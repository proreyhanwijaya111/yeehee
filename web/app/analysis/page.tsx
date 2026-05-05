// Server Component — fetch signal_bundle, hydrate AnalysisClient.
import AnalysisClient from './AnalysisClient'
import { getLatestSignalBundle } from '@/lib/server-api'

export const revalidate = 60

export default async function AnalysisPage() {
  let initialBundle = null
  let serverError: string | null = null
  try {
    initialBundle = await getLatestSignalBundle()
  } catch (e) {
    serverError = e instanceof Error ? e.message : 'Failed to load'
  }
  return <AnalysisClient initialBundle={initialBundle} serverError={serverError} />
}
