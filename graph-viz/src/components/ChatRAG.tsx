import { useState, useRef, useEffect, useCallback } from 'react'
import type { Concept } from '../lib/graphStore'

const API = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000') as string

// Types
interface Source {
  uri:         string
  label:       string
  definition:  string
  country:     string
  year:        string
  scope:       string
  rrf_score:   number
  sources:     string[]
}

type Mode = 'llm_only' | 'vector_rag' | 'graph_rag' | 'agent_rag'

const MODE_LABELS: Record<Mode, string> = {
  llm_only:   'LLM seul',
  vector_rag: 'RAG',
  graph_rag:  'GraphRAG',
  agent_rag:  'Agent IA',
}

const MODE_DESC: Record<Mode, string> = {
  llm_only:   'Le LLM repond depuis ses connaissances, sans retrieval',
  vector_rag: 'ChromaDB uniquement, sans SPARQL ni graphe',
  graph_rag:  'SPARQL + vectoriel + enrichissement graphe',
  agent_rag:  'Le LLM choisit lui-meme quels outils utiliser',
}

interface Message {
  id:       number
  role:     'user' | 'assistant' | 'error'
  content:  string
  mode?:    Mode
  sources?: Source[]
  latency?: number
  eval?:    { context_utilization: number; answer_coverage: number; n_docs_retrieved: number }
  loading?: boolean
}

// Helpers

// Transforme [1][2] en badges cliquables et retourne du texte formaté
function AnswerText({ text, sources }: { text: string; sources: Source[] }) {
  // Remplace [N] par un badge
  const parts = text.split(/(\[\d+\])/g)
  return (
    <p className="cr-answer-text">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/)
        if (m) {
          const idx = Number(m[1]) - 1
          const src = sources[idx]
          return (
            <sup key={i} className="cr-cite" title={src?.label ?? ''}>
              {part}
            </sup>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </p>
  )
}

// Source card
function SourceCard({ src, n, onOpen }: { src: Source; n: number; onOpen: (uri: string) => void }) {
  return (
    <div className="cr-source-card" onClick={() => onOpen(src.uri)} title="Cliquer pour voir la fiche RDF">
      <span className="cr-source-n">[{n}]</span>
      <div className="cr-source-body">
        <span className="cr-source-label">{src.label || src.uri.split('/').at(-1)}</span>
        <div className="cr-source-chips">
          {src.country && <span className="cr-chip">{src.country}</span>}
          {src.year    && <span className="cr-chip">{src.year}</span>}
          {src.sources?.includes('vector')  && <span className="cr-chip cr-chip-v">sémantique</span>}
          {src.sources?.includes('sparql')  && <span className="cr-chip cr-chip-s">SPARQL</span>}
          {src.sources?.includes('threshold') && <span className="cr-chip cr-chip-t">Seuils KG</span>}
          <span className="cr-chip cr-chip-score">{(src.rrf_score * 100).toFixed(1)}</span>
        </div>
        {src.definition && (
          <p className="cr-source-def">{src.definition.slice(0, 160)}{src.definition.length > 160 ? '…' : ''}</p>
        )}
      </div>
    </div>
  )
}

// Bulles
function MessageBubble({ msg, onOpenConcept }: { msg: Message; onOpenConcept: (uri: string) => void }) {
  const [showSources, setShowSources] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="cr-msg cr-msg--user">
        <div className="cr-bubble cr-bubble--user">{msg.content}</div>
      </div>
    )
  }

  if (msg.role === 'error') {
    return (
      <div className="cr-msg cr-msg--error">
        <div className="cr-bubble cr-bubble--error"> {msg.content}</div>
      </div>
    )
  }

  if (msg.loading) {
    return (
      <div className="cr-msg cr-msg--assistant">
        <div className="cr-bubble cr-bubble--assistant">
          <span className="cr-typing"><span /><span /><span /></span>
        </div>
      </div>
    )
  }

  const structuredSources = msg.sources?.filter(
    s => s.sources?.includes('threshold')
  ) ?? []

  return (
    <div className="cr-msg cr-msg--assistant">
      <div className="cr-bubble cr-bubble--assistant">

        {/* Bandeau seuils injectés */}
        {structuredSources.length > 0 && (
          <div className="cr-threshold-banner">
            <span className="cr-threshold-icon"></span>
            <span>
              Seuils KG injectés:{' '}
              {structuredSources.map(s => s.label || s.country || '?').join(', ')}
            </span>
          </div>
        )}

        <AnswerText text={msg.content} sources={msg.sources ?? []} />

        {/* Footer : mode + sources + métriques */}
        <div className="cr-msg-footer">
          {msg.mode && (
            <span className={`cr-mode-badge cr-mode-badge--${msg.mode}`}
                  title={MODE_DESC[msg.mode]}>
              {MODE_LABELS[msg.mode]}
            </span>
          )}
          {(msg.sources?.length ?? 0) > 0 && (
            <button className="cr-sources-toggle"
              onClick={() => setShowSources(s => !s)}>
              {showSources ? '▲' : '▼'} {msg.sources!.length} source{msg.sources!.length > 1 ? 's' : ''}
            </button>
          )}
          {msg.latency != null && (
            <span className="cr-latency">{msg.latency.toFixed(0)} ms</span>
          )}
          {msg.eval && msg.eval.n_docs_retrieved > 0 && (
            <span className="cr-eval" title="Utilisation contexte / Couverture réponse">
              ctx {Math.round((msg.eval.context_utilization ?? 0) * 100)}%
              &nbsp;·&nbsp;
              cov {Math.round((msg.eval.answer_coverage ?? 0) * 100)}%
            </span>
          )}
        </div>

        {showSources && msg.sources && (
          <div className="cr-sources-list">
            {msg.sources.map((src, i) => (
              <SourceCard key={src.uri} src={src} n={i + 1} onOpen={onOpenConcept} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Suggestions de départ
const SUGGESTIONS = [
  'What is the FAO definition of forest?',
  'What is the crown cover threshold for Madagascar?',
  'What are the UNFCCC criteria for afforestation?',
  'What minimum area and crown cover does Germany use to define forest?',
  'Compare deforestation definitions across FAO, UNFCCC and IPCC',
  'Which countries in Africa define forest with a minimum crown cover of 30%?',
]

// Composant principal
export interface ChatRAGProps {
  onOpenConcept: (uri: string) => void
}

export function ChatRAG({ onOpenConcept }: ChatRAGProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [apiOk, setApiOk]       = useState<boolean | null>(null)
  const [mode, setMode]         = useState<Mode>('graph_rag')
  const nextId                  = useRef(0)
  const bottomRef               = useRef<HTMLDivElement>(null)
  const inputRef                = useRef<HTMLTextAreaElement>(null)

  // Vérifier la santé de l'API au montage
  useEffect(() => {
    fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setApiOk(data.index_ready === true))
      .catch(() => setApiOk(false))
  }, [])

  // Auto-scroll vers le bas
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const addMessage = useCallback((msg: Omit<Message, 'id'>) => {
    const id = nextId.current++
    setMessages(prev => [...prev, { ...msg, id }])
    return id
  }, [])

  const updateMessage = useCallback((id: number, patch: Partial<Message>) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...patch } : m))
  }, [])

  async function send(query: string) {
    if (!query.trim() || loading) return
    setInput('')
    setLoading(true)

    addMessage({ role: 'user', content: query })
    const loadId = addMessage({ role: 'assistant', content: '', loading: true })

    try {
      const res = await fetch(`${API}/api/query`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ query: query.trim(), top_k: 6, mode }),
        signal:  AbortSignal.timeout(120_000),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail ?? `HTTP ${res.status}`)
      }

      const data = await res.json()

      updateMessage(loadId, {
        loading:  false,
        content:  data.answer,
        mode:     data.mode ?? mode,
        sources:  data.sources,
        latency:  data.latency_ms,
        eval:     data.evaluation,
      })

    } catch (e: any) {
      updateMessage(loadId, {
        loading: false,
        role:    'error',
        content: e.message?.includes('fetch')
          ? "L'API RAG n'est pas accessible. Assurez-vous que le serveur est démarré sur le port 8000."
          : (e.message ?? 'Erreur inconnue'),
      })
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  const isEmpty = messages.length === 0

  return (
    <div className="cr-root">

      {/* ── Header ── */}
      <div className="cr-header">
        <div className="cr-header-left">
          <span className="cr-header-title">Chat RAG</span>
          <span className="cr-header-sub">Interface graphique</span>
        </div>
        <div className="cr-header-right">
          {/* Sélecteur de mode */}
          <div className="cr-mode-selector" title="Mode de retrieval pour la prochaine question">
            {(['llm_only', 'vector_rag', 'graph_rag', 'agent_rag'] as Mode[]).map(m => (
              <button
                key={m}
                className={`cr-mode-btn ${mode === m ? 'cr-mode-btn--active' : ''}`}
                onClick={() => setMode(m)}
                title={MODE_DESC[m]}
              >
                {MODE_LABELS[m]}
              </button>
            ))}
          </div>
          {apiOk === null && <span className="cr-status cr-status--loading">Vérification API…</span>}
          {apiOk === true  && <span className="cr-status cr-status--ok">● API prête</span>}
          {apiOk === false && <span className="cr-status cr-status--err">● API hors ligne</span>}
        </div>
      </div>

      {/* ── Zone messages ── */}
      <div className="cr-messages">
        {isEmpty ? (
          <div className="cr-welcome">
            <div className="cr-welcome-icon"></div>
            <h2 className="cr-welcome-title">RAG4OneForest</h2>
            <p className="cr-welcome-sub">
              Posez une question sur les définitions de forêts<br/>
            </p>
            <div className="cr-suggestions">
              {SUGGESTIONS.map(s => (
                <button key={s} className="cr-suggestion" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} onOpenConcept={onOpenConcept} />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Zone de saisie ── */}
      <div className="cr-input-area">
        <textarea
          ref={inputRef}
          className="cr-input"
          placeholder="Posez votre question… "
          value={input}
          rows={2}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={loading}
        />
        <button
          className="cr-send-btn"
          onClick={() => send(input)}
          disabled={loading || !input.trim()}>
          {loading ? '…' : '↑'}
        </button>
      </div>

    </div>
  )
}
