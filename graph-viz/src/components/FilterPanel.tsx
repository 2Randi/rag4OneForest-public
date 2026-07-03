import { type GraphStore, type Concept, getConceptColor } from '../lib/graphStore'

interface Props {
  store: GraphStore
  query:     string;  setQuery:     (v: string) => void
  category:  string;  setCategory:  (v: string) => void
  country:   string;  setCountry:   (v: string) => void
  year:      string;  setYear:      (v: string) => void
  orgUri:    string;  setOrgUri:    (v: string) => void
  scopeUri:  string;  setScopeUri:  (v: string) => void
  maxConcepts: number
  onMaxConceptsChange: (n: number) => void
  results: Concept[]
  onSelectConcept: (c: Concept) => void
  onReset: () => void
}

export function FilterPanel({
  store, query, setQuery, category, setCategory,
  country, setCountry, year, setYear,
  orgUri, setOrgUri, scopeUri, setScopeUri,
  maxConcepts, onMaxConceptsChange,
  results, onSelectConcept, onReset,
}: Props) {
  const stats     = store.getStats()
  const countries = store.getCountries()
  const years     = store.getYears()
  const orgs      = store.getOrgCollections()
  const scopes    = store.getScopeCollections()

  const hasFilter = query.trim().length >= 1 || category || country
    || year || orgUri || scopeUri

  function clearFilters() {
    setQuery(''); setCategory(''); setCountry('')
    setYear(''); setOrgUri(''); setScopeUri('')
  }

  return (
    <aside className="filter-panel">

      <div className="fp-form">
        <div className="fp-form-title">Filtres</div>

        {/* Mot-clé */}
        <div className="fp-field">
          <label className="fp-label">Mot-clé</label>
          <input className="fp-input" type="text" placeholder="Nom ou identifiant…"
            value={query} onChange={e => setQuery(e.target.value)} />
        </div>

        {/* Catégorie — format "Forest (42)" */}
        <div className="fp-field">
          <label className="fp-label">Catégorie</label>
          <select className="fp-select" value={category} onChange={e => setCategory(e.target.value)}>
            <option value="">Concepts ({stats.totalConcepts})</option>
            {stats.byCategory.map(cat => (
              <option key={cat.uri} value={cat.uri}>{cat.label} ({cat.count})</option>
            ))}
          </select>
        </div>

        {/* Pays */}
        <div className="fp-field">
          <label className="fp-label">Pays</label>
          <select className="fp-select" value={country} onChange={e => setCountry(e.target.value)}>
            <option value="">Pays ({countries.length})</option>
            {countries.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* Année */}
        {/* <div className="fp-field">
          <label className="fp-label">Année</label>
          <select className="fp-select" value={year} onChange={e => setYear(e.target.value)}>
            <option value="">Toutes</option>
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        </div> */}

        {/* Organisation */}
        <div className="fp-field">
          <label className="fp-label">Organisation</label>
          <select className="fp-select" value={orgUri} onChange={e => setOrgUri(e.target.value)}>
            <option value="">Orgs ({orgs.length})</option>
            {orgs.map(o => (
              <option key={o.uri} value={o.uri}>
                {o.label}{o.count > 0 ? ` (${o.count})` : ''}
              </option>
            ))}
          </select>
        </div>

        {/* Portée / Type (Scope_ et Type_) */}
        <div className="fp-field">
          <label className="fp-label">Portée</label>
          <select className="fp-select" value={scopeUri} onChange={e => setScopeUri(e.target.value)}>
            <option value="">Portées ({scopes.length})</option>
            {scopes.map(s => (
              <option key={s.uri} value={s.uri}>
                {s.label}{s.count > 0 ? ` (${s.count})` : ''}
              </option>
            ))}
          </select>
        </div>

        {/* Slider */}
        <div className="fp-field">
          <label className="fp-label">
            Concepts / catégorie
            <span className="fp-slider-val">{maxConcepts}</span>
          </label>
          <input type="range" className="fp-slider"
            min={5} max={300} step={5}
            value={maxConcepts}
            onChange={e => onMaxConceptsChange(Number(e.target.value))} />
          <div className="fp-slider-ticks">
            <span>5</span><span>150</span><span>300</span>
          </div>
        </div>

        <div className="fp-actions">
          <button className="fp-btn fp-btn-clear" onClick={clearFilters}
            disabled={!hasFilter}>Effacer filtres</button>
          <button className="fp-btn fp-btn-reset" onClick={onReset}>Réinitialiser vue</button>
        </div>
      </div>

      {/* Résultats */}
      {results.length > 0 && (
        <div className="fp-results">
          <div className="fp-results-title">
            {results.length} résultat{results.length > 1 ? 's' : ''} - affichés dans le graphe
          </div>
          <ul className="fp-results-list">
            {results.map(c => {
              const color = getConceptColor(c)
              return (
                <li key={c.uri} className="fp-result-item"
                  onClick={() => onSelectConcept(c)} title={c.uri}>
                  <span className="fp-result-dot" style={{ background: color }} />
                  <div className="fp-result-text">
                    <span className="fp-result-label">{c.shortId}</span>
                    {c.label !== c.shortId && <span className="fp-result-sub">{c.label}</span>}
                  </div>
                  <div className="fp-result-chips">
                    {c.country && <span className="fp-result-chip">{c.country}</span>}
                    {c.year    && <span className="fp-result-chip">{c.year}</span>}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {hasFilter && results.length === 0 && (
        <div className="fp-hint">Aucun résultat.</div>
      )}
      {!hasFilter && (
        <div className="fp-hint">
        
        </div>
      )}
    </aside>
  )
}
