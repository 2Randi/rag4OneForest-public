import { Parser } from 'n3'

// Namespaces
const SKOS = 'http://www.w3.org/2004/02/skos/core#'
const DCT  = 'http://purl.org/dc/terms/'
const RDF  = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'

const P = {
  type:          `${RDF}type`,
  prefLabel:     `${SKOS}prefLabel`,
  altLabel:      `${SKOS}altLabel`,
  definition:    `${SKOS}definition`,
  scopeNote:     `${SKOS}scopeNote`,
  broader:       `${SKOS}broader`,
  narrower:      `${SKOS}narrower`,
  related:       `${SKOS}related`,
  broadMatch:    `${SKOS}broadMatch`,
  narrowMatch:   `${SKOS}narrowMatch`,
  relatedMatch:  `${SKOS}relatedMatch`,
  exactMatch:    `${SKOS}exactMatch`,
  closeMatch:    `${SKOS}closeMatch`,
  inScheme:      `${SKOS}inScheme`,
  member:        `${SKOS}member`,
  hasTopConcept: `${SKOS}hasTopConcept`,
  topConceptOf:  `${SKOS}topConceptOf`,
  Concept:       `${SKOS}Concept`,
  ConceptScheme: `${SKOS}ConceptScheme`,
  Collection:    `${SKOS}Collection`,
  spatial:       `${DCT}spatial`,
  date:          `${DCT}date`,
  creator:       `${DCT}creator`,
  source:        `${DCT}source`,
}

const STRUCTURAL_PREDICATES = new Set([
  P.broader, P.narrower, P.related,
  P.broadMatch, P.narrowMatch, P.relatedMatch,
  P.exactMatch, P.closeMatch,
  P.inScheme, P.member, P.hasTopConcept, P.topConceptOf,
])

// Exported types
export type EdgeType =
  | 'broadMatch' | 'broader' | 'narrower' | 'related'
  | 'exactMatch' | 'inScheme' | 'member' | 'hasTopConcept'
  | 'topConceptOf' | 'relatedMatch' | 'narrowMatch' | 'closeMatch' | 'other'

export interface Concept {
  uri: string
  label: string        // prefLabel (human-readable)
  shortId: string      // URI fragment — unique identifier shown on graph nodes
  kind: 'topConcept' | 'concept' | 'scheme' | 'collection' | 'resource' | 'literal'
  topConceptUri: string | null
  topConceptLabel: string | null
  prefLabels: string[]
  altLabels: string[]
  definitions: string[]
  scopeNotes: string[]
  country: string | null
  year: string | null
  creator: string | null
  sources: string[]
  outLiterals: { predicate: string; value: string; lang?: string; datatype?: string }[]
  degree: number
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: EdgeType
  label?: string  // predicate display name (shown on edge in canvas)
}

export interface GraphStats {
  totalConcepts: number
  totalEdges: number
  byCategory: { label: string; uri: string; count: number; color: string }[]
  byEdgeType: { type: string; count: number }[]
  topConceptCount: number
  collectionCount: number
}

// Labels des 17 collections organisation
const ORG_LABELS: Record<string, string> = {
  'Org_KP':        'Kyoto Protocol',
  'Org_FAO':       'FAO / UN-FAO',
  'Org_IPCC':      'IPCC',
  'Org_EU':        'European Union / EC',
  'Org_WorldBank': 'World Bank',
  'Org_SAF':       'Society of American Foresters',
  'Org_UNEP':      'UNEP',
  'Org_NIR':       'National Inventory Reports',
  'Org_NFI':       'National Forest Inventories',
  'Org_UNFCCC':    'UNFCCC',
  'Org_USDAFS':    'USDA Forest Service',
  'Org_IUCN':      'IUCN',
  'Org_ITTO':      'ITTO',
  'Org_IUFRO':     'IUFRO',
  'Org_WWF':       'WWF',
  'Org_WRI':       'WRI',
  'Org_WCMC':      'WCMC / UNEP-WCMC',
}

// Colors
export const CATEGORY_COLORS: Record<string, string> = {
  Forest:            '#3fb950',
  Deforestation:     '#f85149',
  Afforestation:     '#58a6ff',
  Reforestation:     '#e3b341',
  Woodland:          '#d29922',
  Tree:              '#a371f7',
  LandCover:         '#56d364',
  LandUse:           '#79c0ff',
  Plantation:        '#fb923c',
  NativeForest:      '#4ade80',
  NaturalForest:     '#34d399',
  SemiNaturalForest: '#6ee7b7',
  NonForest:         '#9ca3af',
  Degradation:       '#ef4444',
  Regeneration:      '#86efac',
}

export function getConceptColor(c: Concept): string {
  if (c.kind === 'topConcept') {
    const frag = c.uri.split('/').at(-1) ?? ''
    return CATEGORY_COLORS[frag] ?? '#8b949e'
  }
  if (c.topConceptUri) {
    const frag = c.topConceptUri.split('/').at(-1) ?? ''
    return CATEGORY_COLORS[frag] ?? '#8b949e'
  }
  return '#8b949e'
}

// Helpers
function predicateToEdgeType(predicate: string): EdgeType {
  const local = predicate.split('#').at(-1) ?? predicate.split('/').at(-1) ?? ''
  const known: EdgeType[] = [
    'broadMatch','broader','narrower','related','exactMatch',
    'inScheme','member','hasTopConcept','topConceptOf',
    'relatedMatch','narrowMatch','closeMatch',
  ]
  return (known as string[]).includes(local) ? (local as EdgeType) : 'other'
}

const EX_BASE = 'http://example.org/forest-def/'

function shortFrag(uri: string): string {
  if (uri.startsWith(EX_BASE)) return 'ex:' + uri.slice(EX_BASE.length)
  if (uri.includes('#'))        return uri.split('#').at(-1)!
  return uri.split('/').at(-1) ?? uri
}

// GraphStore
export class GraphStore {
  private concepts = new Map<string, Concept>()
  private edges: GraphEdge[] = []
  // source URI → edges originating from source
  private outEdges = new Map<string, GraphEdge[]>()
  // target URI → edges pointing to target
  private inEdges  = new Map<string, GraphEdge[]>()

  constructor(turtle: string) {
    this._parse(turtle)
  }

  // Internal build
  private _parse(turtle: string): void {
    const quads = new Parser().parse(turtle)

    // Mutable raw maps built during first pass
    type Raw = {
      uri: string
      kinds: Set<string>
      prefLabels: string[]
      altLabels: string[]
      definitions: string[]
      scopeNotes: string[]
      country: string | null
      countryUri: string | null
      year: string | null
      creator: string | null
      sources: string[]
      outLiterals: { predicate: string; value: string; lang?: string; datatype?: string }[]
    }
    const raws = new Map<string, Raw>()
    const pendingEdges: { subject: string; object: string; predicate: string }[] = []

    const getOrCreate = (uri: string): Raw => {
      if (!raws.has(uri)) {
        raws.set(uri, {
          uri,
          kinds: new Set(),
          prefLabels: [],
          altLabels: [],
          definitions: [],
          scopeNotes: [],
          country: null,
          countryUri: null,
          year: null,
          creator: null,
          sources: [],
          outLiterals: [],
        })
      }
      return raws.get(uri)!
    }

    for (const quad of quads) {
      const subject   = quad.subject.value
      const predicate = quad.predicate.value
      const object    = quad.object

      const raw = getOrCreate(subject)

      if (predicate === P.type && object.termType === 'NamedNode') {
        raw.kinds.add(object.value)
      }

      if (object.termType === 'Literal') {
        const lit = object.value
        const lang = (object as { language?: string }).language ?? undefined

        if (predicate === P.prefLabel) {
          // Labels anglais en premier pour que label = prefLabel @en
          if (lang === 'en' || !lang) raw.prefLabels.unshift(lit)
          else raw.prefLabels.push(lit)
        } else if (predicate === P.altLabel)   raw.altLabels.push(lit)
        else if (predicate === P.definition) raw.definitions.push(lit)
        else if (predicate === P.scopeNote)  raw.scopeNotes.push(lit)
        else if (predicate === P.spatial)    raw.country = lit
        else if (predicate === P.date)       raw.year    = lit
        else if (predicate === P.creator)    raw.creator = lit
        else if (predicate === P.source)     raw.sources.push(lit)

        const datatype = (object as { datatype?: { value?: string } }).datatype?.value?.split('#').at(-1) ?? undefined
        raw.outLiterals.push({ predicate, value: lit, lang, datatype })
      }

      if (object.termType === 'NamedNode' && STRUCTURAL_PREDICATES.has(predicate)) {
        pendingEdges.push({ subject, object: object.value, predicate })
        // ensure target node exists
        getOrCreate(object.value)
      }

      // dct:spatial pointe vers un pays maintenant, plus du texte direct.
      // on résout le prefLabel plus tard, une fois tous les quads lus
      if (object.termType === 'NamedNode' && predicate === P.spatial) {
        raw.countryUri = object.value
        getOrCreate(object.value)
      }
    }

    // Identify top concepts: those with skos:topConceptOf or skos:Concept that
    // have at least one hasTopConcept pointing to them from the scheme.
    const topConceptUris = new Set<string>()
    for (const pe of pendingEdges) {
      if (pe.predicate === P.topConceptOf) topConceptUris.add(pe.subject)
      if (pe.predicate === P.hasTopConcept) topConceptUris.add(pe.object)
    }

    // Build broadMatch map: child → topConcept URI
    const broadMatchToTop = new Map<string, string>()
    for (const pe of pendingEdges) {
      if (pe.predicate === P.broadMatch && topConceptUris.has(pe.object)) {
        broadMatchToTop.set(pe.subject, pe.object)
      }
    }

    // Build final Concept map
    for (const [uri, raw] of raws) {
      let kind: Concept['kind'] = 'resource'
      if (raw.kinds.has(P.ConceptScheme)) kind = 'scheme'
      else if (raw.kinds.has(P.Collection)) kind = 'collection'
      else if (topConceptUris.has(uri)) kind = 'topConcept'
      else if (raw.kinds.has(P.Concept)) kind = 'concept'

      const label =
        raw.prefLabels.find(l => l) ??
        raw.altLabels.find(l => l) ??
        shortFrag(uri)
      const shortId = shortFrag(uri)

      const topConceptUri = broadMatchToTop.get(uri) ?? null

      const country = raw.country ??
        (raw.countryUri ? raws.get(raw.countryUri)?.prefLabels.find(l => l) ?? null : null)

      this.concepts.set(uri, {
        uri,
        label,
        shortId,
        kind,
        topConceptUri,
        topConceptLabel: null, // filled below
        prefLabels: raw.prefLabels,
        altLabels: raw.altLabels,
        definitions: raw.definitions,
        scopeNotes: raw.scopeNotes,
        country,
        year: raw.year,
        creator: raw.creator,
        sources: raw.sources,
        outLiterals: raw.outLiterals,
        degree: 0,
      })
    }

    // Fill topConceptLabel
    for (const c of this.concepts.values()) {
      if (c.topConceptUri) {
        const tc = this.concepts.get(c.topConceptUri)
        if (tc) c.topConceptLabel = tc.label
      }
    }

    // Build edges & degree
    let edgeIdx = 0
    const seen = new Set<string>()
    for (const pe of pendingEdges) {
      if (pe.subject === pe.object) continue
      const dedupeKey = `${pe.subject}|${pe.predicate}|${pe.object}`
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)

      const type = predicateToEdgeType(pe.predicate)
      const edge: GraphEdge = {
        id:     `e${edgeIdx++}`,
        source: pe.subject,
        target: pe.object,
        type,
      }
      this.edges.push(edge)

      const src = this.concepts.get(pe.subject)
      const tgt = this.concepts.get(pe.object)
      if (src) src.degree += 1
      if (tgt) tgt.degree += 1

      if (!this.outEdges.has(pe.subject)) this.outEdges.set(pe.subject, [])
      this.outEdges.get(pe.subject)!.push(edge)

      if (!this.inEdges.has(pe.object)) this.inEdges.set(pe.object, [])
      this.inEdges.get(pe.object)!.push(edge)
    }
  }

  // Public API

  getTopConcepts(): Concept[] {
    return [...this.concepts.values()].filter(c => c.kind === 'topConcept')
  }

  // Arêtes entre un ensemble de concepts donnés
  getEdgesBetween(uris: string[]): GraphEdge[] {
    const set = new Set(uris)
    return this.edges.filter(e => set.has(e.source) && set.has(e.target))
  }

  // Arêtes entre top concepts uniquement (pour le graphe global)
  getTopConceptEdges(): GraphEdge[] {
    const topUris = new Set(this.getTopConcepts().map(c => c.uri))
    // Dédupliquer les arêtes symétriques (related A→B et related B→A)
    const seen = new Set<string>()
    return this.edges.filter(e => {
      if (!topUris.has(e.source) || !topUris.has(e.target)) return false
      const key = [e.source, e.target, e.type].sort().join('|')
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  getScheme(): Concept | null {
    return [...this.concepts.values()].find(c => c.kind === 'scheme') ?? null
  }

  getConcept(uri: string): Concept | undefined {
    return this.concepts.get(uri)
  }

  getChildren(uri: string, limit = 60): Concept[] {
    // Children = concepts that have a broadMatch pointing to uri
    const results: Concept[] = []
    for (const c of this.concepts.values()) {
      if (c.topConceptUri === uri) {
        results.push(c)
        if (results.length >= limit) break
      }
    }
    // Also include concepts with skos:broader → uri (via inEdges)
    const broader = this.inEdges.get(uri) ?? []
    for (const e of broader) {
      if (e.type === 'narrower' || e.type === 'broader') {
        const c = this.concepts.get(e.source)
        if (c && !results.find(r => r.uri === c.uri)) {
          results.push(c)
          if (results.length >= limit) break
        }
      }
    }
    return results.slice(0, limit)
  }

  getChildrenWithEdges(uri: string, limit = 40): { nodes: Concept[]; edges: GraphEdge[] } {
    const children = this.getChildren(uri, limit)
    const childUris = new Set([uri, ...children.map(c => c.uri)])
    const parent = this.concepts.get(uri)
    const nodes  = parent ? [parent, ...children] : children
    const edges  = this.edges.filter(
      e => childUris.has(e.source) && childUris.has(e.target)
    )
    return { nodes, edges }
  }

  getNeighborEdges(uri: string): GraphEdge[] {
    return [...(this.outEdges.get(uri) ?? []), ...(this.inEdges.get(uri) ?? [])]
  }

  getNeighbors(uri: string): { nodes: Concept[]; edges: GraphEdge[] } {
    const allEdges = this.getNeighborEdges(uri)
    const neighborUris = new Set<string>()
    for (const e of allEdges) {
      neighborUris.add(e.source)
      neighborUris.add(e.target)
    }
    const nodes: Concept[] = []
    for (const u of neighborUris) {
      const c = this.concepts.get(u)
      if (c) nodes.push(c)
    }
    return { nodes, edges: allEdges }
  }

  search(query: string, limit = 20): Concept[] {
    if (!query.trim()) return []
    const q = query.toLowerCase()
    const results: Concept[] = []
    for (const c of this.concepts.values()) {
      const haystack = [
        c.label,
        ...c.prefLabels,
        ...c.altLabels,
      ].join(' ').toLowerCase()
      if (haystack.includes(q)) {
        results.push(c)
        if (results.length >= limit) break
      }
    }
    return results
  }

  // Expand a concept with ALL its RDF properties:
  //   - object properties → concept circle nodes
  //   - data properties   → literal rectangle nodes (truncated values)
  expandWithLiterals(uri: string): { nodes: Concept[]; edges: GraphEdge[] } {
    const concept = this.concepts.get(uri)
    if (!concept) return { nodes: [], edges: [] }

    const resultNodes: Concept[] = [concept]
    const resultEdges: GraphEdge[] = []

    // Object-property neighbors (concept → concept edges)
    const { nodes: objNodes, edges: objEdges } = this.getNeighbors(uri)
    for (const n of objNodes) {
      if (n.uri !== uri && n.kind !== 'literal') resultNodes.push(n)
    }
    resultEdges.push(...objEdges)

    // Data-property neighbors (concept → literal rectangle nodes)
    const DISPLAY_PREDS: Record<string, string> = {
      [P.prefLabel]:  'prefLabel',
      [P.altLabel]:   'altLabel',
      [P.definition]: 'définition',
      [P.scopeNote]:  'scopeNote',
      [P.spatial]:    'pays',
      [P.date]:       'année',
      [P.creator]:    'auteur',
      [P.source]:     'source',
    }

    let litIdx = 0
    for (const lit of concept.outLiterals) {
      const predLabel = DISPLAY_PREDS[lit.predicate]
      if (!predLabel) continue
      // For definition, truncate to 50 chars; others 35
      const maxLen = lit.predicate === P.definition ? 50 : 35
      const truncVal = lit.value.length > maxLen
        ? lit.value.slice(0, maxLen - 1) + '…'
        : lit.value
      const synUri = `_lit_${litIdx}_${uri}`
      resultNodes.push({
        uri:           synUri,
        label:         truncVal,
        shortId:       truncVal,
        kind:          'literal',
        topConceptUri: null,
        topConceptLabel: null,
        prefLabels:    [],
        altLabels:     [],
        definitions:   [],
        scopeNotes:    [],
        country:       null,
        year:          null,
        creator:       null,
        sources:       [],
        outLiterals:   [],
        degree:        1,
      })
      resultEdges.push({
        id:     `elit_${litIdx}_${uri}`,
        source: uri,
        target: synUri,
        type:   'other',
        label:  predLabel,
      })
      litIdx++
    }

    return { nodes: resultNodes, edges: resultEdges }
  }

  // Collections Scope_ et Type_ (portée et type des définitions)
  getScopeCollections(): { uri: string; key: string; label: string; count: number }[] {
    const LABELS: Record<string, string> = {
      'Scope_General':       'General',
      'Scope_International': 'International',
      'Scope_National':      'National',
      'Scope_State':         'State / Sub-national',
      'Type_Declared':       'Declared type',
      'Type_Ecological':     'Ecological type',
      'Type_Land_cover':     'Land cover',
      'Type_Land_use':       'Land use',
    }
    const results: { uri: string; key: string; label: string; count: number }[] = []
    for (const c of this.concepts.values()) {
      if (c.kind !== 'collection') continue
      const frag = c.uri.split('/').at(-1) ?? ''
      if (!frag.startsWith('Scope_') && !frag.startsWith('Type_')) continue
      const label = LABELS[frag] ?? frag
      const count = (this.outEdges.get(c.uri) ?? []).filter(e => e.type === 'member').length
      results.push({ uri: c.uri, key: frag, label, count })
    }
    return results.sort((a, b) => a.label.localeCompare(b.label))
  }

  getOrgCollections(): { uri: string; key: string; label: string; count: number }[] {
    const results: { uri: string; key: string; label: string; count: number }[] = []
    for (const c of this.concepts.values()) {
      if (c.kind !== 'collection') continue
      const frag = c.uri.split('/').at(-1) ?? ''
      if (!frag.startsWith('Org_')) continue
      const label = ORG_LABELS[frag] ?? frag.replace('Org_', '')
      const count = (this.outEdges.get(c.uri) ?? []).filter(e => e.type === 'member').length
      results.push({ uri: c.uri, key: frag, label, count })
    }
    return results.sort((a, b) => a.label.localeCompare(b.label))
  }

  getCountries(): string[] {
    const set = new Set<string>()
    for (const c of this.concepts.values()) if (c.country) set.add(c.country)
    return [...set].sort()
  }

  getYears(): string[] {
    const set = new Set<string>()
    for (const c of this.concepts.values()) if (c.year) set.add(c.year)
    return [...set].sort()
  }

  getCreators(): string[] {
    const set = new Set<string>()
    for (const c of this.concepts.values()) if (c.creator) set.add(c.creator)
    return [...set].sort()
  }

  getConceptsByFilter(
    opts: { category?: string; country?: string; year?: string; orgUri?: string; scopeUri?: string; query?: string },
    limit = 40
  ): Concept[] {
    const q = opts.query?.toLowerCase() ?? ''
    // Précompute membres des collections filtrées
    const memberSetFor = (collUri: string | undefined): Set<string> | null => {
      if (!collUri) return null
      return new Set(
        (this.outEdges.get(collUri) ?? [])
          .filter(e => e.type === 'member')
          .map(e => e.target)
      )
    }
    const orgMemberUris   = memberSetFor(opts.orgUri)
    const scopeMemberUris = memberSetFor(opts.scopeUri)

    const results: Concept[] = []
    for (const c of this.concepts.values()) {
      if (c.kind !== 'concept' && c.kind !== 'topConcept') continue
      if (opts.category && c.topConceptUri !== opts.category && c.uri !== opts.category) continue
      if (opts.country && c.country !== opts.country) continue
      if (opts.year && c.year !== opts.year) continue
      if (orgMemberUris   && !orgMemberUris.has(c.uri))   continue
      if (scopeMemberUris && !scopeMemberUris.has(c.uri))  continue
      if (q && !c.label.toLowerCase().includes(q) && !c.shortId.toLowerCase().includes(q)) continue
      results.push(c)
      if (results.length >= limit) break
    }
    return results
  }

  getStats(): GraphStats {
    const topConcepts = this.getTopConcepts()
    const allConcepts = [...this.concepts.values()]
    const totalConcepts = allConcepts.filter(c => c.kind === 'concept' || c.kind === 'topConcept').length
    const collectionCount = allConcepts.filter(c => c.kind === 'collection').length

    const byCategory = topConcepts.map(tc => {
      const count = allConcepts.filter(c => c.topConceptUri === tc.uri).length
      const frag  = tc.uri.split('/').at(-1) ?? ''
      return {
        label: tc.label,
        uri:   tc.uri,
        count,
        color: CATEGORY_COLORS[frag] ?? '#8b949e',
      }
    }).sort((a, b) => b.count - a.count)

    const edgeTypeCounts = new Map<string, number>()
    for (const e of this.edges) {
      edgeTypeCounts.set(e.type, (edgeTypeCounts.get(e.type) ?? 0) + 1)
    }
    const byEdgeType = [...edgeTypeCounts.entries()]
      .map(([type, count]) => ({ type, count }))
      .sort((a, b) => b.count - a.count)

    return {
      totalConcepts,
      totalEdges: this.edges.length,
      byCategory,
      byEdgeType,
      topConceptCount: topConcepts.length,
      collectionCount,
    }
  }
}
