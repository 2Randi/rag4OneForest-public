import { useMemo, useState } from 'react'
import { type GraphStore, type Concept, getConceptColor } from '../lib/graphStore'

interface DetailPanel {
  title: string
  concepts: Concept[]
  color?: string
}

interface SectionId {
  id: string
  label: string
}

const SECTIONS: SectionId[] = [
  { id: 'categories',  label: 'Catégories' },
  { id: 'relations',   label: 'Relations SKOS' },
  { id: 'countries',   label: 'Couverture géographique' },
  { id: 'period',      label: 'Période temporelle' },
  { id: 'orgs',        label: 'Organisations' },
  { id: 'scope',       label: 'Portée / Type' },
  { id: 'topDegree',   label: 'Concepts connectés' },
]

function pct(n: number, total: number) {
  return total ? Math.round((n / total) * 100) : 0
}

// Mini bar horizontal
function Bar({ count, max, color, active }: {
  count: number; max: number; color: string; active?: boolean
}) {
  return (
    <div className="sv-bar-track">
      <div className="sv-bar-fill"
        style={{ width: `${(count / max) * 100}%`, background: color, opacity: active === false ? 0.3 : 1 }} />
    </div>
  )
}

// Item concept dans le panneau détail
function ConceptItem({ c, onOpen }: { c: Concept; onOpen: (c: Concept) => void }) {
  const color = getConceptColor(c)
  return (
    <div className="sv-concept-item" onClick={() => onOpen(c)}>
      <span className="sv-concept-dot" style={{ background: color }} />
      <div className="sv-concept-text">
        <span className="sv-concept-id">{c.shortId}</span>
        {c.label !== c.shortId && <span className="sv-concept-label">{c.label}</span>}
      </div>
      <div className="sv-concept-chips">
        {c.country && <span className="sv-chip">{c.country}</span>}
        {c.year    && <span className="sv-chip">{c.year}</span>}
        {c.definitions.length > 0 && <span className="sv-chip sv-chip-def">déf</span>}
      </div>
    </div>
  )
}

// Section accordéon
function Section({ id, label, open, onToggle, children }: {
  id: string; label: string
  open: boolean; onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className={`sv-section ${open ? 'sv-section--open' : ''}`}>
      <button className="sv-section-header" onClick={onToggle}>
        <span className="sv-section-label">{label}</span>
        <span className="sv-section-chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="sv-section-body">{children}</div>}
    </div>
  )
}

export interface StatsViewProps {
  store: GraphStore
  onOpenConcept?: (c: Concept) => void
}

export function StatsView({ store, onOpenConcept }: StatsViewProps) {
  // Sections ouvertes (accordéon — aucune par défaut)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set())
  // Panneau détail
  const [detail, setDetail]     = useState<DetailPanel | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(null)
  // Filtre période
  const [yearFrom, setYearFrom] = useState('')
  const [yearTo,   setYearTo]   = useState('')

  function toggleSection(id: string) {
    setOpenSections(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // Stats de base
  const base = useMemo(() => store.getStats(), [store])

  const enriched = useMemo(() => {
    const countryMap = new Map<string, number>()
    const yearMap    = new Map<string, number>()
    let withDef = 0, withCountry = 0, withYear = 0

    for (const c of (store as any).concepts.values() as IterableIterator<Concept>) {
      if (c.kind !== 'concept' && c.kind !== 'topConcept') continue
      if (c.definitions.length > 0) withDef++
      if (c.country) { withCountry++; countryMap.set(c.country, (countryMap.get(c.country) ?? 0) + 1) }
      if (c.year)    { withYear++;    yearMap.set(c.year,       (yearMap.get(c.year)       ?? 0) + 1) }
    }

    const byCountry = [...countryMap.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)

    const byYear = [...yearMap.entries()]
      .map(([year, count]) => ({ year, count }))
      .sort((a, b) => a.year.localeCompare(b.year))

    const allYears = byYear.map(y => y.year)
    const yearMin  = allYears[0]   ?? '—'
    const yearMax  = allYears.at(-1) ?? '—'

    const allConcepts: Concept[] = [...(store as any).concepts.values()]
    const topDegree = allConcepts
      .filter(c => c.kind === 'concept' || c.kind === 'topConcept')
      .sort((a, b) => b.degree - a.degree)
      .slice(0, 15)
      .map(c => ({ concept: c, degree: c.degree }))

    const byOrg   = store.getOrgCollections().filter(o => o.count > 0).sort((a, b) => b.count - a.count)
    const byScope = store.getScopeCollections().filter(s => s.count > 0).sort((a, b) => b.count - a.count)

    return {
      withDef, withCountry, withYear,
      byCountry, byYear, allYears, yearMin, yearMax,
      topDegree, byOrg, byScope,
    }
  }, [store])

  // Années filtrées pour le graphique période
  const filteredYears = useMemo(() => {
    return enriched.byYear.filter(y => {
      if (yearFrom && y.year < yearFrom) return false
      if (yearTo   && y.year > yearTo)   return false
      return true
    })
  }, [enriched.byYear, yearFrom, yearTo])

  const T      = base.totalConcepts
  const maxCat = Math.max(...base.byCategory.map(c => c.count), 1)
  const maxEdge = Math.max(...base.byEdgeType.map(e => e.count), 1)
  const maxCty  = Math.max(...enriched.byCountry.map(c => c.count), 1)
  const maxYear = Math.max(...filteredYears.map(y => y.count), 1)
  const maxOrg  = Math.max(...enriched.byOrg.map(o => o.count), 1)
  const maxScope = Math.max(...enriched.byScope.map(s => s.count), 1)
  const maxDeg  = Math.max(...enriched.topDegree.map(d => d.degree), 1)

  // Helpers sélection / détail
  function selectBar(key: string, title: string, concepts: Concept[], color?: string) {
    if (activeKey === key) { setDetail(null); setActiveKey(null); return }
    setDetail({ title, concepts, color })
    setActiveKey(key)
  }

  function selectCategory(uri: string, label: string, color: string) {
    selectBar(`cat:${uri}`, `Catégorie : ${label}`,
      store.getConceptsByFilter({ category: uri }, 60), color)
  }
  function selectCountry(name: string) {
    selectBar(`cty:${name}`, `Pays : ${name}`,
      store.getConceptsByFilter({ country: name }, 60))
  }
  function selectOrg(uri: string, label: string) {
    selectBar(`org:${uri}`, `Organisation : ${label}`,
      store.getConceptsByFilter({ orgUri: uri }, 60))
  }
  function selectScope(uri: string, label: string) {
    selectBar(`scp:${uri}`, `Portée : ${label}`,
      store.getConceptsByFilter({ scopeUri: uri }, 60))
  }
  function selectYear(year: string) {
    selectBar(`yr:${year}`, `Année : ${year}`,
      store.getConceptsByFilter({ year }, 60))
  }
  function selectTopDeg(c: Concept) {
    const key = `deg:${c.uri}`
    if (activeKey === key) { setDetail(null); setActiveKey(null); return }
    const { nodes } = store.getNeighbors(c.uri)
    setDetail({
      title: `Voisins de ${c.shortId}`,
      concepts: nodes.filter(n => n.kind !== 'literal'),
      color: getConceptColor(c),
    })
    setActiveKey(key)
  }

  return (
    <div className="stats-view">

      {/* ── KPIs ────────────────────────────────────────────────────────── */}
      <div className="sv-kpi-row">
        <div className="sv-kpi">
          <span className="sv-kpi-value">{T.toLocaleString()}</span>
          <span className="sv-kpi-label">Concepts</span>
        </div>
        <div className="sv-kpi">
          <span className="sv-kpi-value">{base.totalEdges.toLocaleString()}</span>
          <span className="sv-kpi-label">Relations</span>
        </div>
        <div className="sv-kpi">
          <span className="sv-kpi-value">{base.topConceptCount}</span>
          <span className="sv-kpi-label">Top Concepts</span>
        </div>
        <div className="sv-kpi">
          <span className="sv-kpi-value">{base.collectionCount}</span>
          <span className="sv-kpi-label">Collections</span>
        </div>
        <div className="sv-kpi">
          <span className="sv-kpi-value">{enriched.byCountry.length}</span>
          <span className="sv-kpi-label">Pays couverts</span>
        </div>
        <div className="sv-kpi">
          <span className="sv-kpi-value">{enriched.yearMin} – {enriched.yearMax}</span>
          <span className="sv-kpi-label">Période</span>
        </div>
      </div>

      {/* ── Qualité ─────────────────────────────────────────────────────── */}
      <div className="sv-quality-row">
        <div className="sv-quality-title">Qualité du Knowledge Graph</div>
        <div className="sv-quality-bars">
          {[
            { label: 'Avec définition', n: enriched.withDef,     color: '#16a34a' },
            { label: 'Avec pays',       n: enriched.withCountry, color: '#ea580c' },
            { label: 'Avec année',      n: enriched.withYear,    color: '#d97706' },
          ].map(({ label, n, color }) => (
            <div key={label} className="sv-quality-item">
              <span className="sv-quality-label">{label}</span>
              <div className="sv-quality-track">
                <div className="sv-quality-fill" style={{ width: `${pct(n, T)}%`, background: color }} />
              </div>
              <span className="sv-quality-pct">{pct(n, T)}%</span>
              <span className="sv-quality-n">({n})</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Accordéon de sections ────────────────────────────────────────── */}
      <div className="sv-accordion">
        {SECTIONS.map(sec => (
          <Section key={sec.id} id={sec.id} label={sec.label}
            open={openSections.has(sec.id)}
            onToggle={() => toggleSection(sec.id)}>

            {/* ── CATÉGORIES ── */}
            {sec.id === 'categories' && (
              <div className="sv-bars">
                {base.byCategory.map(cat => {
                  const k = `cat:${cat.uri}`
                  return (
                    <div key={cat.uri}
                      className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                      onClick={() => selectCategory(cat.uri, cat.label, cat.color)}>
                      <span className="sv-bar-label" style={{ color: cat.color, fontWeight: 700 }}>{cat.label}</span>
                      <Bar count={cat.count} max={maxCat} color={cat.color}
                        active={activeKey === null || activeKey === k} />
                      <span className="sv-bar-count">{cat.count}</span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── RELATIONS ── */}
            {sec.id === 'relations' && (
              <div className="sv-bars">
                {base.byEdgeType.map(et => (
                  <div key={et.type} className="sv-bar-row">
                    <span className="sv-bar-label" style={{ fontFamily: 'ui-monospace,monospace', fontSize: 11 }}>
                      skos:{et.type}
                    </span>
                    <Bar count={et.count} max={maxEdge} color="#1d4ed8" />
                    <span className="sv-bar-count">{et.count}</span>
                  </div>
                ))}
              </div>
            )}

            {/* ── PAYS ── */}
            {sec.id === 'countries' && (
              <div className="sv-bars sv-bars--scroll">
                {enriched.byCountry.map(c => {
                  const k = `cty:${c.name}`
                  return (
                    <div key={c.name}
                      className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                      onClick={() => selectCountry(c.name)}>
                      <span className="sv-bar-label">{c.name}</span>
                      <Bar count={c.count} max={maxCty} color="#ea580c"
                        active={activeKey === null || activeKey === k} />
                      <span className="sv-bar-count">{c.count}</span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── PÉRIODE ── */}
            {sec.id === 'period' && (
              <div className="sv-period-wrap">
                <div className="sv-period-form">
                  <label className="sv-period-label">De</label>
                  <select className="sv-period-select" value={yearFrom}
                    onChange={e => setYearFrom(e.target.value)}>
                    <option value="">Début</option>
                    {enriched.allYears.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                  <label className="sv-period-label">À</label>
                  <select className="sv-period-select" value={yearTo}
                    onChange={e => setYearTo(e.target.value)}>
                    <option value="">Fin</option>
                    {enriched.allYears.map(y => <option key={y} value={y}>{y}</option>)}
                  </select>
                  {(yearFrom || yearTo) && (
                    <button className="sv-period-clear"
                      onClick={() => { setYearFrom(''); setYearTo('') }}>X</button>
                  )}
                </div>
                <div className="sv-bars sv-bars--scroll" style={{ marginTop: 10 }}>
                  {filteredYears.length === 0
                    ? <p style={{ color: '#64748b', fontSize: 12 }}>Aucune donnée sur cette période.</p>
                    : filteredYears.map(y => {
                        const k = `yr:${y.year}`
                        return (
                          <div key={y.year}
                            className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                            onClick={() => selectYear(y.year)}>
                            <span className="sv-bar-label" style={{ fontVariantNumeric: 'tabular-nums' }}>{y.year}</span>
                            <Bar count={y.count} max={maxYear} color="#d97706"
                              active={activeKey === null || activeKey === k} />
                            <span className="sv-bar-count">{y.count}</span>
                          </div>
                        )
                      })
                  }
                </div>
              </div>
            )}

            {/* ── ORGANISATIONS ── */}
            {sec.id === 'orgs' && (
              <div className="sv-bars sv-bars--scroll">
                {enriched.byOrg.map(o => {
                  const k = `org:${o.uri}`
                  return (
                    <div key={o.uri}
                      className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                      onClick={() => selectOrg(o.uri, o.label)}>
                      <span className="sv-bar-label">{o.label}</span>
                      <Bar count={o.count} max={maxOrg} color="#9333ea"
                        active={activeKey === null || activeKey === k} />
                      <span className="sv-bar-count">{o.count}</span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── PORTÉE / TYPE ── */}
            {sec.id === 'scope' && (
              <div className="sv-bars">
                {enriched.byScope.map(s => {
                  const k = `scp:${s.uri}`
                  const color = s.key.startsWith('Scope_') ? '#0891b2' : '#16a34a'
                  return (
                    <div key={s.uri}
                      className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                      onClick={() => selectScope(s.uri, s.label)}>
                      <span className="sv-bar-label">{s.label}</span>
                      <Bar count={s.count} max={maxScope} color={color}
                        active={activeKey === null || activeKey === k} />
                      <span className="sv-bar-count">{s.count}</span>
                    </div>
                  )
                })}
              </div>
            )}

            {/* ── TOP CONNECTÉS ── */}
            {sec.id === 'topDegree' && (
              <div className="sv-bars">
                {enriched.topDegree.map(({ concept: c, degree }) => {
                  const color = getConceptColor(c)
                  const k = `deg:${c.uri}`
                  return (
                    <div key={c.uri}
                      className={`sv-bar-row sv-bar-row--clickable ${activeKey === k ? 'sv-bar-row--active' : ''}`}
                      onClick={() => selectTopDeg(c)}>
                      <span className="sv-bar-label" style={{ color, fontWeight: 700 }}>{c.shortId}</span>
                      <Bar count={degree} max={maxDeg} color={color}
                        active={activeKey === null || activeKey === k} />
                      <span className="sv-bar-count">{degree}</span>
                    </div>
                  )
                })}
              </div>
            )}

          </Section>
        ))}
      </div>

      {/* ── Panneau détail ────────────────────────────────────────────────── */}
      {detail && (
        <div className="sv-detail">
          <div className="sv-detail-header">
            <span className="sv-detail-title">{detail.title}</span>
            <span className="sv-detail-count">{detail.concepts.length} concept{detail.concepts.length > 1 ? 's' : ''}</span>
            <button className="sv-detail-close" onClick={() => { setDetail(null); setActiveKey(null) }}>X</button>
          </div>
          <div className="sv-detail-list">
            {detail.concepts.length === 0
              ? <p style={{ color: '#64748b', padding: '12px', fontSize: 12 }}>Aucun concept trouvé.</p>
              : detail.concepts.map(c => (
                  <ConceptItem key={c.uri} c={c} onOpen={onOpenConcept ?? (() => {})} />
                ))
            }
          </div>
        </div>
      )}

    </div>
  )
}
