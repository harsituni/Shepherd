import { useCallback, useEffect, useState } from 'react'

// Written by ./demo.sh into dashboard/public/demo-join.json (Vite serves /public at /).
const JOIN_PATH = '/demo-join.json'
const POLL_MS = 3000

async function loadJoin() {
  const res = await fetch(`${JOIN_PATH}?t=${Date.now()}`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`join ${res.status}`)
  return res.json()
}

export default function JoinQr() {
  const [info, setInfo] = useState(null) // null = none yet, object = file contents
  const [copied, setCopied] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setInfo(await loadJoin())
    } catch {
      // Keep the last good payload if a poll fails mid-demo.
    }
  }, [])

  useEffect(() => {
    const first = setTimeout(refresh, 0)
    const id = setInterval(refresh, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(id)
    }
  }, [refresh])

  const active = info?.active && info?.joinUrl
  const qrSrc = info?.qrDataUrl || (active
    ? `https://api.qrserver.com/v1/create-qr-code/?size=220x220&ecc=M&data=${encodeURIComponent(info.joinUrl)}`
    : null)

  const copy = async () => {
    if (!info?.joinUrl) return
    try {
      await navigator.clipboard.writeText(info.joinUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

  return (
    <section className="join-qr" aria-label="Phone join">
      <div className="join-qr-head">
        <h2 className="join-qr-title">Phone join</h2>
        {active ? (
          <span className="join-qr-live" role="status">
            Live
          </span>
        ) : (
          <span className="join-qr-idle" role="status">
            Offline
          </span>
        )}
      </div>

      {active && qrSrc ? (
        <>
          <img className="join-qr-img" src={qrSrc} width={220} height={220} alt="QR code to open Shepherd on a phone" />
          <p className="join-qr-hint">Scan to open the phone app (cellular OK). Fresh for this ./demo.sh run.</p>
          <button type="button" className="btn-outline join-qr-copy" onClick={copy}>
            {copied ? 'Copied' : 'Copy join URL'}
          </button>
          <p className="join-qr-url num" title={info.joinUrl}>
            {info.joinUrl}
          </p>
        </>
      ) : (
        <p className="join-qr-hint">
          Run <code>./demo.sh</code> on this laptop to put a scannable QR here. Laptop-only:{' '}
          <code>http://localhost:5174</code>
        </p>
      )}
    </section>
  )
}
