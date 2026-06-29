import React from 'react'
import type { GraphStore } from '../lib/graphStore'
import { getConceptColor } from '../lib/graphStore'

const SKOS = 'http://www.w3.org/2004/02/skos/core#'
const DCT  = 'http://purl.org/dc/terms/'
const RDF  = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'

// Prédicats → littéraux (rectangles)
const LIT_PREDS: Record<string, string> = {
  [`${SKOS}prefLabel`]:  'skos:prefLabel',
  [`${SKOS}altLabel`]:   'skos:altLabel',
  [`${SKOS}definition`]: 'skos:definition',
  [`${SKOS}scopeNote`]:  'skos:scopeNote',
  [`${SKOS}note`]:       'skos:note',
  [`${DCT}spatial`]:     'dct:spatial',
  [`${DCT}date`]:        'dct:date',
  [`${DCT}creator`]:     'dct:creator',
  [`${DCT}source`]:      'dct:source',
  [`${RDF}type`]:        'rdf:type',
}
const PRED_ORDER: Record<string, number> = {
  'skos:prefLabel': 0, 'skos:altLabel': 1, 'skos:definition': 2,
  'skos:scopeNote': 3, 'skos:note': 4, 'dct:spatial': 5,
  'dct:date': 6, 'dct:creator': 7, 'dct:source': 8, 'rdf:type': 9,
}

// Couleur par prédicat (chaque littéral a sa propre couleur)
const PRED_COLORS: Record<string, string> = {
  'skos:prefLabel':  '#2563eb',
  'skos:altLabel':   '#0891b2',
  'skos:definition': '#16a34a',
  'skos:scopeNote':  '#0d9488',
  'skos:note':       '#65a30d',
  'dct:spatial':     '#ea580c',
  'dct:date':        '#d97706',
  'dct:creator':     '#9333ea',
  'dct:source':      '#db2777',
  'rdf:type':        '#4338ca',
}
function litColor(pred: string): string {
  return PRED_COLORS[pred] ?? '#475569'
}

// Prédicats objet (arcs vers d'autres concepts → ovales)
const OBJ_TYPES = new Set([
  'broadMatch','broader','related','exactMatch','relatedMatch',
  'narrowMatch','closeMatch','narrower','topConceptOf','inScheme',
  'member','hasTopConcept',
])

// Format exact comme dans le .ttl : "value"@en ou "value"^^xsd:anyURI etc.
function ttlFmt(value: string, lang?: string, datatype?: string): string {
  const v = `"${value}"`
  if (lang) return v + `@${lang}`
  if (datatype && datatype !== 'langString') {
    const short = datatype.includes('#')
      ? datatype.split('#').at(-1)!
      : (datatype.split('/').at(-1) ?? datatype)
    return v + `^^xsd:${short}`
  }
  return v
}

// Découpage en lignes — gère les mots longs (URLs) par découpage forcé
function wrapLines(text: string, maxChars: number, maxLines = 8): { lines: string[]; truncated: boolean } {
  if (text.length <= maxChars) return { lines: [text], truncated: false }
  const lines: string[] = []
  let cur = ''

  const pushWord = (w: string) => {
    // Mot plus long que maxChars → découper caractère par caractère
    if (w.length > maxChars) {
      if (cur) { lines.push(cur); cur = '' }
      let rem = w
      while (rem.length > 0 && lines.length < maxLines) {
        const chunk = rem.slice(0, maxChars)
        rem = rem.slice(maxChars)
        if (rem.length > 0) lines.push(chunk)
        else cur = chunk
      }
    } else {
      const next = cur ? `${cur} ${w}` : w
      if (next.length > maxChars) { lines.push(cur); cur = w }
      else cur = next
    }
  }

  for (const w of text.split(' ')) {
    if (lines.length >= maxLines) break
    pushWord(w)
  }
  if (cur && lines.length < maxLines) lines.push(cur)

  const total = text.split(' ').join('').length
  const shown = lines.join('').length
  return { lines: lines.slice(0, maxLines), truncated: shown < total }
}

// Point sur le bord de l'ellipse dans la direction de (tx,ty)
function ellipsePt(cx: number, cy: number, rx: number, ry: number, tx: number, ty: number): [number, number] {
  const dx = tx - cx, dy = ty - cy
  const t = 1 / (Math.sqrt((dx / rx) ** 2 + (dy / ry) ** 2) || 0.001)
  return [cx + t * dx, cy + t * dy]
}

interface Props {
  store: GraphStore
  uri: string
  onBack: () => void
  onNavigate: (uri: string) => void
}

export function ConceptRDFView({ store, uri, onBack, onNavigate }: Props) {
  const concept = store.getConcept(uri)
  if (!concept) return (
    <div className="rdf-view">
      <button className="rdf-back-btn" onClick={onBack}>← Retour</button>
    </div>
  )

  const cColor = getConceptColor(concept)

  // Littéraux
  const lits = concept.outLiterals
    .filter(l => LIT_PREDS[l.predicate])
    .map(l => ({ pred: LIT_PREDS[l.predicate], value: l.value, lang: l.lang, datatype: l.datatype }))
    .sort((a, b) => (PRED_ORDER[a.pred] ?? 99) - (PRED_ORDER[b.pred] ?? 99))

  // Concepts liés (arcs objet) — max 8 affichés
  const MAX_RELS = 8
  type RelItem = {
    pred: string; peerUri: string; shortId: string
    color: string; dir: 'out' | 'in'
  }
  const rels: RelItem[] = []
  let totalRels = 0
  const seen = new Set<string>()
  for (const e of store.getNeighborEdges(uri)) {
    if (!OBJ_TYPES.has(e.type)) continue
    const isOut = e.source === uri
    const peerUri = isOut ? e.target : e.source
    if (peerUri === uri) continue
    const key = `${e.type}|${peerUri}`
    if (seen.has(key)) continue
    seen.add(key)
    const peer = store.getConcept(peerUri)
    if (!peer || peer.kind === 'literal') continue
    totalRels++
    if (rels.length < MAX_RELS) {
      rels.push({ pred: 'skos:' + e.type, peerUri, shortId: peer.shortId, color: getConceptColor(peer), dir: isOut ? 'out' : 'in' })
    }
  }

  // Dimensions
  const PAD_L    = 32
  const PAD_R    = 90
  const PAD_T    = 36
  const LIT_W    = 380
  const FONT     = 13
  const ACCENT   = 6
  const TEXT_W   = LIT_W - ACCENT - 12 - 12   // barre + padG + padD
  const CHARS    = Math.floor(TEXT_W / 7.5)    // ~7.5px/char monospace 13px
  const LINE_H   = FONT + 8
  const V_PAD    = 12
  const LIT_GAP  = 14
  const H_GAP    = 90

  const OVAL_RX  = Math.min(Math.max(80, concept.shortId.length * 5.5 + 16), 140)
  const OVAL_RY  = 40
  const REL_RX   = 72
  const REL_RY   = 30
  const REL_GAP  = 20

  // Hauteur de chaque rectangle littéral — taille calculée sur le contenu réel
  const litH = lits.map(l => {
    const { lines } = wrapLines(ttlFmt(l.value, l.lang, l.datatype), CHARS, 8)
    return V_PAD + lines.length * LINE_H + V_PAD
  })
  const litTotal = litH.reduce((s, h, i) => s + h + (i < litH.length - 1 ? LIT_GAP : 0), 0)
  const relTotal = rels.length > 0 ? rels.length * (REL_RY * 2 + REL_GAP) - REL_GAP : 0
  const contentH = Math.max(litTotal, relTotal, OVAL_RY * 2 + 20)
  const cy       = PAD_T + contentH / 2

  const ovalCx = PAD_L + LIT_W + H_GAP + OVAL_RX
  const relCx  = ovalCx + OVAL_RX + H_GAP + REL_RX
  const W      = relCx + REL_RX + PAD_R
  const H      = contentH + PAD_T * 2 + 20

  // Centres Y des littéraux
  let acc = 0
  const litYs = litH.map((h, i) => {
    const y = cy - litTotal / 2 + acc + h / 2
    acc += h + (i < litH.length - 1 ? LIT_GAP : 0)
    return y
  })

  // Centres Y des concepts liés
  const relYs = rels.map((_, i) => cy - relTotal / 2 + i * (REL_RY * 2 + REL_GAP) + REL_RY)

  return (
    <div className="rdf-view">
      <div className="rdf-header">
        <button className="rdf-back-btn" onClick={onBack}>← Retour au graphe</button>
        <div className="rdf-header-info">
          <span className="rdf-kind-badge" style={{ background: cColor + '20', color: cColor, borderColor: cColor }}>
            {concept.kind}
          </span>
          <span className="rdf-concept-title" style={{ color: cColor }}>{concept.shortId}</span>
          <code className="rdf-concept-uri">{uri}</code>
        </div>
      </div>

      {totalRels > MAX_RELS && (
        <p className="rdf-rel-hint">
          {rels.length} relations affichees sur {totalRels}
        </p>
      )}

      <div className="rdf-canvas-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}
          style={{ display: 'block', background: '#f8fafc', borderRadius: 12, boxShadow: '0 2px 14px #0002' }}>
          <defs>
            {/* Flèche standard (pointe à la fin) */}
            <marker id="arr" viewBox="0 -4 8 8" refX="7" refY="0"
              markerWidth="5" markerHeight="5" orient="auto">
              <path d="M0,-4L8,0L0,4" fill="context-stroke" />
            </marker>
          </defs>

          {/* ══ LITTÉRAUX — colonne gauche ══════════════════════════════════ */}
          {lits.map((lit, i) => {
            const rh     = litH[i]
            const ry     = litYs[i]
            const rx     = PAD_L
            const color  = litColor(lit.pred)
            const fmtVal = ttlFmt(lit.value, lit.lang, lit.datatype)
            const { lines, truncated } = wrapLines(fmtVal, CHARS, 8)
            const clipId = `clip-lit-${i}`

            // Arc : oval → bord droit du rect (flèche pointe sur le rect)
            const [ax1, ay1] = ellipsePt(ovalCx, cy, OVAL_RX, OVAL_RY, rx + LIT_W, ry)
            const ax2 = rx + LIT_W
            const ay2 = ry
            const mx  = (ax1 + ax2) / 2
            const my  = (ay1 + ay2) / 2

            return (
              <g key={`lit-${i}`}>
                {/* Arc tiret : oval → rect */}
                <line x1={ax1} y1={ay1} x2={ax2} y2={ay2}
                  stroke={color} strokeWidth={1.4} strokeDasharray="5 3"
                  markerEnd="url(#arr)" />
                {/* Label prédicat sur l'arc — texte seul */}
                <text x={mx} y={my - 5} textAnchor="middle"
                  fontSize={10} fill={color}
                  fontFamily="ui-monospace,monospace" fontWeight="700"
                  stroke="#f8fafc" strokeWidth="3.5" paintOrder="stroke">
                  {lit.pred}
                </text>

                {/* Rectangle littéral */}
                <clipPath id={clipId}>
                  <rect x={rx + ACCENT} y={ry - rh / 2} width={LIT_W - ACCENT} height={rh} />
                </clipPath>
                <rect x={rx} y={ry - rh / 2} width={LIT_W} height={rh}
                  rx={6} fill={color + '0e'} stroke={color} strokeWidth={1.3} />
                <rect x={rx} y={ry - rh / 2} width={ACCENT} height={rh}
                  rx={3} fill={color} />

                {/* Valeur TTL — clippée dans le rect */}
                <g clipPath={`url(#${clipId})`}>
                  {lines.map((line, li) => (
                    <text key={li}
                      x={rx + ACCENT + 9}
                      y={ry - rh / 2 + V_PAD + (li + 1) * LINE_H}
                      fontSize={FONT} fill="#1e293b"
                      fontFamily="ui-monospace,monospace">
                      {line}{li === lines.length - 1 && truncated ? '…' : ''}
                    </text>
                  ))}
                </g>
                <title>{lit.pred}: {lit.value}</title>
              </g>
            )
          })}

          {/* ══ OVALE central ═══════════════════════════════════════════════ */}
          <ellipse cx={ovalCx} cy={cy} rx={OVAL_RX} ry={OVAL_RY}
            fill={cColor + '22'} stroke={cColor} strokeWidth={3} />
          <text x={ovalCx} y={cy - 6} textAnchor="middle"
            fontSize={15} fontWeight="800" fill={cColor}
            stroke="#f8fafc" strokeWidth="3" paintOrder="stroke">
            {concept.shortId.length > 22 ? concept.shortId.slice(0, 20) + '…' : concept.shortId}
          </text>
          {concept.label !== concept.shortId && (
            <text x={ovalCx} y={cy + 13} textAnchor="middle"
              fontSize={11} fill={cColor + 'bb'}
              stroke="#f8fafc" strokeWidth="2.5" paintOrder="stroke">
              {concept.label.length > 26 ? concept.label.slice(0, 24) + '…' : concept.label}
            </text>
          )}

          {/* ══ CONCEPTS LIÉS — colonne droite ══════════════════════════════ */}
          {rels.map((rel, i) => {
            const oy    = relYs[i]
            const rCol  = rel.color

            const [ox1, oy1] = ellipsePt(ovalCx, cy, OVAL_RX, OVAL_RY, relCx, oy)
            const [ox2, oy2] = ellipsePt(relCx, oy, REL_RX, REL_RY, ovalCx, cy)

            const sx = rel.dir === 'out' ? ox1 : ox2
            const sy = rel.dir === 'out' ? oy1 : oy2
            const ex = rel.dir === 'out' ? ox2 : ox1
            const ey = rel.dir === 'out' ? oy2 : oy1

            const mx = (ox1 + ox2) / 2
            const my = (oy1 + oy2) / 2

            const lbl = rel.shortId.length > 18 ? rel.shortId.slice(0, 16) + '…' : rel.shortId

            return (
              <g key={`rel-${i}`} style={{ cursor: 'pointer' }}
                onClick={() => onNavigate(rel.peerUri)}>
                <title>{rel.dir === 'in' ? rel.shortId + ' → ' : ''}{rel.pred}{rel.dir === 'out' ? ' → ' + rel.shortId : ''}</title>

                {/* Arc avec flèche dans le bon sens */}
                <line x1={sx} y1={sy} x2={ex} y2={ey}
                  stroke={rCol} strokeWidth={2} markerEnd="url(#arr)" />

                {/* Label prédicat sur l'arc — texte seul */}
                <text x={mx} y={my - 5} textAnchor="middle"
                  fontSize={10} fill={rCol}
                  fontFamily="ui-monospace,monospace" fontWeight="700"
                  stroke="#f8fafc" strokeWidth="3.5" paintOrder="stroke">
                  {rel.pred}
                </text>

                {/* Ovale du concept lié */}
                <ellipse cx={relCx} cy={oy} rx={REL_RX} ry={REL_RY}
                  fill={rCol + '20'} stroke={rCol} strokeWidth={2.5} />
                <text x={relCx} y={oy + 5} textAnchor="middle"
                  fontSize={12} fontWeight="700" fill={rCol}
                  stroke="#f8fafc" strokeWidth="2.5" paintOrder="stroke">
                  {lbl}
                </text>
              </g>
            )
          })}

          {lits.length === 0 && rels.length === 0 && (
            <text x={ovalCx} y={cy + 80} textAnchor="middle" fontSize={12} fill="#94a3b8">
              Aucune propriété pour ce concept
            </text>
          )}
        </svg>
      </div>
    </div>
  )
}
