import { use, useMemo, useState, useCallback, useEffect } from 'react'
import { GraphStore, type Concept, type GraphEdge } from './lib/graphStore'
import { GraphCanvas } from './components/GraphCanvas'
import { FilterPanel } from './components/FilterPanel'
import { StatsView } from './components/StatsView'
import { ConceptRDFView } from './components/ConceptRDFView'
import { ChatRAG } from './components/ChatRAG'

const graphPromise = fetch('/forest_kg.ttl').then(r => r.text())

type ViewMode = 'graph' | 'rdf' | 'stats' | 'chat'

function GraphApp({ turtle }: { turtle: string }) {
  const store = useMemo(() => new GraphStore(turtle), [turtle])

  // State graphe
  const [viewMode,     setViewMode]     = useState<ViewMode>('graph')
  const [detailUri,    setDetailUri]    = useState<string | null>(null)
  const [maxConcepts,  setMaxConcepts]  = useState(80)
  const [visibleNodes, setVisibleNodes] = useState<Concept[]>(() => {
    const tops = store.getTopConcepts()
    const scheme = store.getScheme()
    return scheme ? [scheme, ...tops] : tops
  })
  const [visibleEdges, setVisibleEdges] = useState<GraphEdge[]>(() => store.getTopConceptEdges())
  const [expandedUris, setExpandedUris] = useState<Set<string>>(new Set())
  const [selectedUri,  setSelectedUri]  = useState<string | null>(null)
  const [searchHL,     setSearchHL]     = useState<Set<string>>(new Set())

  // State filtres (ici, dans App.tsx)
  const [filterQuery,    setFilterQuery]    = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterCountry,  setFilterCountry]  = useState('')
  const [filterYear,     setFilterYear]     = useState('')
  const [filterOrgUri,   setFilterOrgUri]   = useState('')
  const [filterScopeUri, setFilterScopeUri] = useState('')

  const hasFilter = filterQuery.trim() !== '' || filterCategory !== ''
    || filterCountry !== '' || filterYear !== ''
    || filterOrgUri !== '' || filterScopeUri !== ''

  const filterResults = useMemo(() => {
    if (!hasFilter) return [] as Concept[]
    return store.getConceptsByFilter({
      query:    filterQuery.trim()  || undefined,
      category: filterCategory      || undefined,
      country:  filterCountry       || undefined,
      year:     filterYear          || undefined,
      orgUri:   filterOrgUri        || undefined,
      scopeUri: filterScopeUri      || undefined,
    }, 60)
  }, [filterQuery, filterCategory, filterCountry, filterYear, filterOrgUri, filterScopeUri, store, hasFilter])

  // Synchronise le graphe avec les résultats de recherche
  useEffect(() => {
    if (!hasFilter || filterResults.length === 0) {
      // Pas de filtre ou aucun résultat → graphe initial (top concepts)
      const tops   = store.getTopConcepts()
      const scheme = store.getScheme()
      setVisibleNodes(scheme ? [scheme, ...tops] : tops)
      setVisibleEdges(store.getTopConceptEdges())
      setSearchHL(new Set())
      return
    }

    // Filtre actif → seulement les résultats + leurs arêtes entre eux
    const resultUris  = filterResults.map(c => c.uri)
    const resultEdges = store.getEdgesBetween(resultUris)
    setVisibleNodes(filterResults)
    setVisibleEdges(resultEdges)
    setSearchHL(new Set(resultUris))
    setViewMode('graph')
  }, [filterResults, hasFilter, store])

  // Expand top concept dans le graphe
  const expandNode = useCallback((uri: string, limitOverride?: number) => {
    const concept = store.getConcept(uri)
    if (!concept) return
    const result = (concept.kind === 'topConcept' || concept.kind === 'scheme')
      ? store.getChildrenWithEdges(uri, limitOverride ?? maxConcepts)
      : store.getNeighbors(uri)
    setVisibleNodes(prev => {
      const ex = new Set(prev.map(n => n.uri))
      return [...prev, ...result.nodes.filter(n => !ex.has(n.uri))]
    })
    setVisibleEdges(prev => {
      const ex = new Set(prev.map(e => e.id))
      return [...prev, ...result.edges.filter(e => !ex.has(e.id))]
    })
    setExpandedUris(prev => new Set([...prev, uri]))
  }, [store, maxConcepts])

  // Clic nœud : top concept → expand, concept → vue RDF
  const handleNodeClick = useCallback((uri: string) => {
    const c = store.getConcept(uri)
    if (!c) return
    setSelectedUri(uri)
    setSearchHL(new Set([uri]))
    if (c.kind === 'topConcept' || c.kind === 'scheme' || c.kind === 'collection') {
      if (!expandedUris.has(uri)) expandNode(uri)
      setViewMode('graph')
    } else {
      setDetailUri(uri)
      setViewMode('rdf')
    }
  }, [store, expandedUris, expandNode])

  // Double clic → vue RDF (tous types)
  const handleNodeDblClick = useCallback((uri: string) => {
    const c = store.getConcept(uri)
    if (!c) return
    setSelectedUri(uri)
    setDetailUri(uri)
    setViewMode('rdf')
  }, [store])

  // Clic sur résultat liste → vue RDF
  const handleSelectConcept = useCallback((c: Concept) => {
    setSelectedUri(c.uri)
    setDetailUri(c.uri)
    setViewMode('rdf')
  }, [])

  const handleNavigate = useCallback((uri: string) => {
    setDetailUri(uri)
    setSelectedUri(uri)
  }, [])

  const handleBackToGraph = useCallback(() => setViewMode('graph'), [])

  const handleReset = useCallback(() => {
    const tops = store.getTopConcepts()
    const scheme = store.getScheme()
    setVisibleNodes(scheme ? [scheme, ...tops] : tops)
    setVisibleEdges(store.getTopConceptEdges())
    setExpandedUris(new Set())
    setSelectedUri(null)
    setSearchHL(new Set())
    setViewMode('graph')
    setDetailUri(null)
    // Effacer aussi les filtres
    setFilterQuery(''); setFilterCategory(''); setFilterCountry('')
    setFilterYear(''); setFilterOrgUri(''); setFilterScopeUri('')
  }, [store])

  const legendCategories = useMemo(() => store.getStats().byCategory, [store])

  return (
    <div className="app-root">

      <header className="app-header">
        <span className="app-logo">RAG4OneForest KG</span>
        <nav className="app-nav">
          <button className={`app-nav-btn ${viewMode === 'graph' ? 'active' : ''}`}
            onClick={() => { setViewMode('graph'); setDetailUri(null) }}>
            Graphe global
          </button>
          {viewMode === 'rdf' && detailUri && (
            <button className="app-nav-btn active" onClick={() => {}}>
              Vue RDF : {store.getConcept(detailUri)?.shortId ?? '…'}
            </button>
          )}
          <button className={`app-nav-btn ${viewMode === 'stats' ? 'active' : ''}`}
            onClick={() => setViewMode('stats')}>
            Statistiques
          </button>
          <button className={`app-nav-btn ${viewMode === 'chat' ? 'active' : ''}`}
            onClick={() => setViewMode('chat')}>
            Chat RAG
          </button>
        </nav>
        <span className="app-header-hint">
          Clic : déplier &nbsp;·&nbsp; Double clic : vue RDF
        </span>
      </header>

      <div className="app-body">
        <FilterPanel
          store={store}
          query={filterQuery}       setQuery={setFilterQuery}
          category={filterCategory} setCategory={setFilterCategory}
          country={filterCountry}   setCountry={setFilterCountry}
          year={filterYear}         setYear={setFilterYear}
          orgUri={filterOrgUri}     setOrgUri={setFilterOrgUri}
          scopeUri={filterScopeUri} setScopeUri={setFilterScopeUri}
          maxConcepts={maxConcepts}
          onMaxConceptsChange={setMaxConcepts}
          results={filterResults}
          onSelectConcept={handleSelectConcept}
          onReset={handleReset}
        />

        <main className="app-main">
          {viewMode === 'chat' && (
            <ChatRAG onOpenConcept={uri => {
              setDetailUri(uri); setSelectedUri(uri); setViewMode('rdf')
            }} />
          )}
          {viewMode === 'stats' && (
            <StatsView store={store} onOpenConcept={c => {
              setDetailUri(c.uri); setSelectedUri(c.uri); setViewMode('rdf')
            }} />
          )}
          {viewMode === 'graph' && (
            <GraphCanvas
              nodes={visibleNodes}
              edges={visibleEdges}
              selectedUri={selectedUri}
              onNodeClick={handleNodeClick}
              onNodeDblClick={handleNodeDblClick}
              searchHighlight={searchHL}
            />
          )}
          {viewMode === 'rdf' && detailUri && (
            <ConceptRDFView
              store={store}
              uri={detailUri}
              onBack={handleBackToGraph}
              onNavigate={handleNavigate}
            />
          )}
        </main>
      </div>

      <footer className="app-legend">
        {legendCategories.map(cat => (
          <div key={cat.uri} className="legend-item"
            onClick={() => { expandNode(cat.uri); setViewMode('graph') }}
            title={`Ouvrir ${cat.label} (${cat.count} concepts)`}>
            <span className="legend-dot" style={{ background: cat.color }} />
            <span className="legend-label">{cat.label}</span>
            <span className="legend-count">{cat.count}</span>
          </div>
        ))}
      </footer>

    </div>
  )
}

export function App() {
  const turtle = use(graphPromise)
  return <GraphApp turtle={turtle} />
}
