import { useMemo, useState } from 'react'
import { type GraphStore, getConceptColor } from '../lib/graphStore'

export interface ConceptDetailProps {
  store: GraphStore
  uri: string | null
  onExpand: (uri: string) => void
  onSelect: (uri: string) => void
}

const KIND_LABELS: Record<string, string> = {
  topConcept: 'Top Concept',
  concept:    'Concept',
  scheme:     'Scheme',
  collection: 'Collection',
  resource:   'Resource',
}

const REL_TYPES = ['broadMatch','broader','related','exactMatch','relatedMatch','narrowMatch','closeMatch','narrower']

function shortPred(uri: string): string {
  return uri.split('#').at(-1) ?? uri.split('/').at(-1) ?? uri
}
function truncateUri(uri: string, max = 42): string {
  if (uri.length <= max) return uri
  return uri.slice(0, 18) + '…' + uri.slice(-18)
}

// Section pliable générique
function CollapsibleSection({
  title, count, defaultOpen = true, children,
}: {
  title: string
  count?: number
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="cd-section">
      <button className="cd-section-header" onClick={() => setOpen(o => !o)}>
        <span className="cd-section-title">{title}</span>
        {count !== undefined && (
          <span className="cd-section-count">{count}</span>
        )}
        <span className={`cd-section-chevron${open ? ' cd-section-chevron--open' : ''}`}>
          ▼
        </span>
      </button>
      {open && children}
    </div>
  )
}


export function ConceptDetail({ store, uri, onExpand, onSelect }: ConceptDetailProps) {
  const concept = useMemo(() => (uri ? store.getConcept(uri) : undefined), [store, uri])

  if (!concept) {
    return (
      <aside className="concept-detail">
        <div className="cd-empty">
          <span>Sélectionnez un concept</span>
          <small>Double-clic sur un noeud pour déplier son voisinage</small>
        </div>
      </aside>
    )
  }

  const color = getConceptColor(concept)

  // Relations : on s'arrête dès 6 résolues, on compte juste le reste
  const { relItems, totalRelations } = useMemo(() => {
    const neighbors = store.getNeighbors(concept.uri)
    const items: { uri: string; label: string }[] = []
    let total = 0
    for (const e of neighbors.edges) {
      if (!REL_TYPES.includes(e.type)) continue
      total++
      if (items.length < 6) {
        const peerUri = e.source === concept.uri ? e.target : e.source
        const peer    = store.getConcept(peerUri)
        if (peer) items.push({ uri: peerUri, label: peer.label })
      }
    }
    return { relItems: items, totalRelations: total }
  }, [store, concept.uri])

  // Littéraux RDF (hors définitions et scope notes déjà affichés)
  const SKIP_PREDS = new Set(['definition', 'prefLabel', 'altLabel', 'scopeNote', 'note', 'inScheme'])
  const extraLiterals = concept.outLiterals.filter(
    l => !SKIP_PREDS.has(shortPred(l.predicate))
  ).slice(0, 15)

  return (
    <aside className="concept-detail">
      {/* ── En-tête ── */}
      <div className="cd-header" style={{ borderLeftColor: color }}>
        <h2 className="cd-title">{concept.label}</h2>
        <span className="cd-badge" style={{ background: color + '22', color }}>
          {KIND_LABELS[concept.kind] ?? concept.kind}
        </span>
      </div>
      <div className="cd-uri" title={concept.uri}>{truncateUri(concept.uri)}</div>

      {/* ── Corps scrollable ── */}
      <div className="cd-body">

        {/* Définition */}
        {concept.definitions.length > 0 && (
          <CollapsibleSection title="Définition" defaultOpen={true}>
            <div className="cd-section-body">
              <p className="cd-definition">{concept.definitions[0]}</p>
            </div>
          </CollapsibleSection>
        )}

        {/* Note / scope */}
        {concept.scopeNotes.length > 0 && (
          <CollapsibleSection title="Note" defaultOpen={true}>
            <div className="cd-section-body">
              <p className="cd-definition">{concept.scopeNotes[0]}</p>
            </div>
          </CollapsibleSection>
        )}

        {/* Propriétés */}
        {(concept.prefLabels.length > 0 || concept.altLabels.length > 0 ||
          concept.country || concept.year || concept.creator || concept.sources.length > 0) && (
          <CollapsibleSection title="Propriétés" defaultOpen={true}>
            <div className="cd-chips">
              {concept.prefLabels.map((l, i) => (
                <span key={i} className="cd-chip cd-chip-pref" title="prefLabel">{l}</span>
              ))}
              {concept.altLabels.map((l, i) => (
                <span key={i} className="cd-chip cd-chip-alt" title="altLabel">{l}</span>
              ))}
              {concept.country && (
                <span className="cd-chip cd-chip-meta" title="pays">{concept.country}</span>
              )}
              {concept.year && (
                <span className="cd-chip cd-chip-meta" title="année">{concept.year}</span>
              )}
              {concept.creator && (
                <span className="cd-chip cd-chip-meta" title="créateur">{concept.creator}</span>
              )}
              {concept.sources.map((s, i) => (
                <span key={i} className="cd-chip cd-chip-source" title={s}>
                  {s.length > 30 ? s.slice(0, 28) + '…' : s}
                </span>
              ))}
            </div>
          </CollapsibleSection>
        )}

        {/* Relations sémantiques — 6 max, filtre gauche pour le reste */}
        {totalRelations > 0 && (
          <CollapsibleSection
            title="Relations sémantiques"
            count={totalRelations}
            defaultOpen={true}
          >
            <div className="cd-section-body">
              <div className="cd-rel-list">
                {relItems.map(item => (
                  <button
                    key={item.uri}
                    className="cd-rel-link"
                    onClick={() => { onSelect(item.uri); onExpand(item.uri) }}
                    title={item.uri}
                  >
                    {item.label || shortPred(item.uri)}
                  </button>
                ))}
              </div>
              {totalRelations > 6 && (
                <p className="cd-rel-hint">
                  +{totalRelations - 6} autres — utilisez le filtre a gauche pour explorer
                </p>
              )}
            </div>
          </CollapsibleSection>
        )}

        {/* Littéraux RDF supplémentaires — plié par défaut */}
        {extraLiterals.length > 0 && (
          <CollapsibleSection
            title="Littéraux RDF"
            count={extraLiterals.length}
            defaultOpen={false}
          >
            <div className="cd-section-body">
              <div className="cd-rdf-list">
                {extraLiterals.map((lit, i) => (
                  <div key={i} className="cd-rdf-row">
                    <span className="cd-rdf-pred">{shortPred(lit.predicate)}</span>
                    <span className="cd-rdf-arrow">→</span>
                    <span className="cd-rdf-val">
                      {lit.value.length > 80 ? lit.value.slice(0, 78) + '…' : lit.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </CollapsibleSection>
        )}
      </div>

      {/* ── Action ── */}
      <div className="cd-actions">
        <button className="cd-expand-btn" onClick={() => onExpand(concept.uri)}>
          Déplier le voisinage
        </button>
      </div>
    </aside>
  )
}
