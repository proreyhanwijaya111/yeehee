// Server Component — fetch signal_bundle, hydrate client.
import SignalsClient from './SignalsClient'
import { getLatestSignalBundle } from '@/lib/server-api'

export const revalidate = 60

export default async function SignalsPage() {
  let initialBundle = null
  let serverError: string | null = null
  try {
    initialBundle = await getLatestSignalBundle()
  } catch (e) {
    serverError = e instanceof Error ? e.message : 'Failed to load'
  }
  return <SignalsClient initialBundle={initialBundle} serverError={serverError} />
}
