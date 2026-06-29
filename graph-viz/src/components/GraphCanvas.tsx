import { useEffect, useRef } from 'react'
import * as d3 from 'd3'
import { type Concept, type GraphEdge, getConceptColor } from '../lib/graphStore'

interface SimNode extends d3.SimulationNodeDatum {
  uri: string
  label: string
  shortId: string
  kind: Concept['kind']
  color: string
  r: number
  degree: number
  topConceptUri: string | null
}

interface SimEdge extends d3.SimulationLinkDatum<SimNode> {
  id: string
  type: string
  label?: string
}

export interface Props {
  nodes: Concept[]
  edges: GraphEdge[]
  selectedUri: string | null
  onNodeClick: (uri: string) => void
  onNodeDblClick: (uri: string) => void
  searchHighlight: Set<string>
}

const EDGE_STYLES: Record<string, { stroke: string; width: number; dash: string }> = {
  broadMatch:    { stroke: '#475569', width: 1.8, dash: '' },
  broader:       { stroke: '#475569', width: 1.2, dash: '' },
  narrower:      { stroke: '#475569', width: 1.2, dash: '' },
  related:       { stroke: '#94a3b8', width: 1.2, dash: '5 3' },
  exactMatch:    { stroke: '#2563eb', width: 1.8, dash: '3 2' },
  relatedMatch:  { stroke: '#94a3b8', width: 1,   dash: '5 3' },
  narrowMatch:   { stroke: '#64748b', width: 1,   dash: '4 3' },
  closeMatch:    { stroke: '#94a3b8', width: 1,   dash: '2 4' },
  inScheme:      { stroke: '#cbd5e1', width: 0.6, dash: '' },
  member:        { stroke: '#d97706', width: 1.5, dash: '' },
  hasTopConcept: { stroke: '#cbd5e1', width: 0.6, dash: '' },
  topConceptOf:  { stroke: '#cbd5e1', width: 0.6, dash: '' },
  other:         { stroke: '#94a3b8', width: 0.8, dash: '3 4' },
}

function calcRadius(kind: Concept['kind'], degree: number, shortId: string): number {
  if (kind === 'topConcept') return Math.max(38, shortId.length * 4 + 14)
  if (kind === 'scheme')     return 24
  if (kind === 'collection') return 16
  if (kind === 'literal')    return 20
  return Math.max(22, Math.min(shortId.length * 3.5 + 16, 36))
}

export function GraphCanvas({ nodes, edges, selectedUri, onNodeClick, onNodeDblClick, searchHighlight }: Props) {
  const svgRef          = useRef<SVGSVGElement>(null)
  const simRef          = useRef<d3.Simulation<SimNode, SimEdge> | null>(null)
  const nodeMapRef      = useRef<Map<string, SimNode>>(new Map())
  const zoomRef         = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const edgeLayerRef    = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null)
  const edgeLblLayerRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null)
  const nodeLayerRef    = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null)

  // One-time setup
  useEffect(() => {
    const svgEl = svgRef.current
    if (!svgEl) return
    d3.select(svgEl).selectAll('*').remove()

    const svg = d3.select(svgEl)

    // Arrowhead marker
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 7)
      .attr('refY', 0)
      .attr('markerWidth', 5)
      .attr('markerHeight', 5)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', 'context-stroke')
      .attr('stroke', 'none')

    const viewport = svg.append('g').attr('class', 'viewport')
    edgeLayerRef.current    = viewport.append('g').attr('class', 'edges')
    edgeLblLayerRef.current = viewport.append('g').attr('class', 'edge-labels')
    nodeLayerRef.current    = viewport.append('g').attr('class', 'nodes')

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.04, 8])
      .on('zoom', ev => viewport.attr('transform', ev.transform))
    svg.call(zoom)
    zoomRef.current = zoom

    const sim = d3.forceSimulation<SimNode, SimEdge>()
      .force('link', d3.forceLink<SimNode, SimEdge>([]).id(d => d.uri)
        .distance(d => {
          const s = d.source as SimNode, t = d.target as SimNode
          if (s.kind === 'topConcept' && t.kind === 'topConcept') return 320
          if (s.kind === 'topConcept' || t.kind === 'topConcept') return 200
          return 130
        })
        .strength(0.3))
      .force('charge', d3.forceManyBody<SimNode>().strength(d =>
        d.kind === 'topConcept' ? -1200 : d.kind === 'literal' ? -80 : -250))
      .force('collide', d3.forceCollide<SimNode>().radius(d => d.r + 12))
      .force('center', d3.forceCenter(svgEl.clientWidth / 2, svgEl.clientHeight / 2))
      .alphaDecay(0.025)
    simRef.current = sim

    return () => { sim.stop() }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Data update
  useEffect(() => {
    const sim      = simRef.current
    const edgeL    = edgeLayerRef.current
    const edgeLblL = edgeLblLayerRef.current
    const nodeL    = nodeLayerRef.current
    const svgEl    = svgRef.current
    if (!sim || !edgeL || !edgeLblL || !nodeL || !svgEl) return

    const prev = nodeMapRef.current
    const simNodes: SimNode[] = nodes.map(c => {
      const p = prev.get(c.uri)
      return {
        uri: c.uri, label: c.label, shortId: c.shortId,
        kind: c.kind, color: getConceptColor(c),
        r: calcRadius(c.kind, c.degree, c.shortId),
        degree: c.degree, topConceptUri: c.topConceptUri,
        x: p?.x, y: p?.y, vx: p?.vx, vy: p?.vy,
      }
    })
    const newMap = new Map<string, SimNode>()
    for (const n of simNodes) newMap.set(n.uri, n)
    nodeMapRef.current = newMap

    const simEdges: SimEdge[] = edges
      .filter(e => newMap.has(e.source) && newMap.has(e.target))
      .map(e => ({ ...e }))

    sim.nodes(simNodes)
    const lf = sim.force<d3.ForceLink<SimNode, SimEdge>>('link')
    if (lf) lf.links(simEdges)
    sim.alpha(0.4).restart()

    // Edge lines
    const linkSel = edgeL.selectAll<SVGLineElement, SimEdge>('line.edge')
      .data(simEdges, d => d.id)
    linkSel.exit().remove()
    const linkMerged = linkSel.enter().append('line').attr('class', 'edge').merge(linkSel)
    linkMerged.each(function(d) {
      const s = EDGE_STYLES[d.type] ?? EDGE_STYLES.other
      d3.select(this)
        .attr('stroke', s.stroke)
        .attr('stroke-width', s.width)
        .attr('stroke-dasharray', s.dash)
        .attr('stroke-opacity', 0.85)
        .attr('marker-end', 'url(#arrow)')
    })

    // Edge predicate labels — affichés sur tous les arcs
    const lblSel = edgeLblL.selectAll<SVGTextElement, SimEdge>('text.edge-label')
      .data(simEdges, d => d.id)
    lblSel.exit().remove()
    const lblMerged = lblSel.enter().append('text').attr('class', 'edge-label')
      .text(d => d.label ?? `skos:${d.type}`)
      .merge(lblSel)

    // Nodes
    const nodeSel = nodeL.selectAll<SVGGElement, SimNode>('g.gnode')
      .data(simNodes, d => d.uri)
    nodeSel.exit().remove()
    const nodeEnter = nodeSel.enter().append('g').attr('class', 'gnode')

    nodeEnter.each(function(d) {
      const g = d3.select(this)

      if (d.kind === 'scheme') {
        g.append('rect')
          .attr('x', -36).attr('y', -18).attr('width', 72).attr('height', 36).attr('rx', 8)
          .attr('fill', '#ede9fe').attr('stroke', '#5b21b6').attr('stroke-width', 2.5)
        g.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('font-size', 11).attr('font-weight', '800').attr('fill', '#4c1d95')
          .text(d.shortId.slice(0, 14))

      } else if (d.kind === 'collection') {
        const r = d.r
        const pts = Array.from({ length: 6 }, (_, i) => {
          const a = (Math.PI / 3) * i - Math.PI / 6
          return `${r * Math.cos(a)},${r * Math.sin(a)}`
        }).join(' ')
        g.append('polygon').attr('points', pts)
          .attr('fill', '#cffafe').attr('stroke', '#0e7490').attr('stroke-width', 2)
        g.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('font-size', 9).attr('font-weight', '700').attr('fill', '#164e63')
          .text(d.shortId.slice(0, 10))

      } else if (d.kind === 'literal') {
        const w = Math.max(64, Math.min(d.label.length * 6 + 16, 140))
        g.append('rect')
          .attr('x', -w/2).attr('y', -13).attr('width', w).attr('height', 26).attr('rx', 5)
          .attr('fill', '#1e293b').attr('stroke', '#475569').attr('stroke-width', 1.5)
        g.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('font-size', 9).attr('fill', '#e2e8f0')
          .text(d.label)

      } else if (d.kind === 'topConcept') {
        // Large CIRCLE — shortId complet, police adaptée au rayon
        g.append('circle').attr('r', d.r)
          .attr('fill', d.color + '45').attr('stroke', d.color).attr('stroke-width', 3)
        // Taille de police : remplit le cercle sans couper
        const fs = Math.min(14, Math.max(10, Math.floor((d.r * 1.7) / (d.shortId.length * 0.6))))
        g.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('font-size', fs).attr('font-weight', '800').attr('fill', d.color)
          .style('paint-order', 'stroke').style('stroke', 'white').style('stroke-width', '3px')
          .text(d.shortId)

      } else {
        // Regular concept — CIRCLE with shortId complet
        g.append('circle').attr('r', d.r)
          .attr('fill', d.color + '35').attr('stroke', d.color).attr('stroke-width', 2)
        const fs = Math.min(12, Math.max(9, Math.floor((d.r * 1.7) / (d.shortId.length * 0.6))))
        g.append('text')
          .attr('text-anchor', 'middle').attr('dy', '0.35em')
          .attr('font-size', fs).attr('font-weight', '700').attr('fill', d.color)
          .style('paint-order', 'stroke').style('stroke', 'white').style('stroke-width', '2.5px')
          .text(d.shortId)
      }

      // Full label tooltip
      g.append('title').text(`${d.shortId}\n${d.label !== d.shortId ? d.label : ''} (${d.kind})`)
    })

    const nodeMerged = nodeEnter.merge(nodeSel)

    // Selection ring
    nodeMerged.each(function(d) {
      d3.select(this).select('.sel-ring').remove()
      if (d.uri === selectedUri && d.kind !== 'literal') {
        d3.select(this).append('circle')
          .attr('class', 'sel-ring')
          .attr('r', d.r + 7)
          .attr('fill', 'none')
          .attr('stroke', '#1d4ed8')
          .attr('stroke-width', 2.5)
          .attr('stroke-dasharray', '4 2')
          .attr('pointer-events', 'none')
      }
    })

    // Hover
    nodeMerged
      .style('cursor', d => d.kind === 'literal' ? 'default' : 'pointer')
      .on('mouseenter', function(_, hovered) {
        const connected = new Set([hovered.uri])
        simEdges.forEach(e => {
          const s = (e.source as SimNode).uri
          const t = (e.target as SimNode).uri
          if (s === hovered.uri || t === hovered.uri) { connected.add(s); connected.add(t) }
        })
        nodeMerged.style('opacity', n => connected.has(n.uri) ? null : '0.08')
        linkMerged.style('opacity', e => {
          const s = (e.source as SimNode).uri, t = (e.target as SimNode).uri
          return s === hovered.uri || t === hovered.uri ? null : '0.06'
        })
        lblMerged.style('opacity', e => (e.source as SimNode).uri === hovered.uri ? null : '0.06')
      })
      .on('mouseleave', () => {
        nodeMerged.style('opacity', null)
        linkMerged.style('opacity', null)
        lblMerged.style('opacity', null)
      })

    // Simple clic → expand ou vue RDF (selon le kind)
    nodeMerged.on('click', function(event, d) {
      event.stopPropagation()
      if (d.kind === 'literal') return
      onNodeClick(d.uri)
      const svgW = svgEl.clientWidth, svgH = svgEl.clientHeight
      const zb = zoomRef.current
      if (zb && d.x != null && d.y != null) {
        d3.select(svgEl).transition().duration(400).call(
          zb.transform,
          d3.zoomIdentity.translate(svgW/2, svgH/2).scale(1.5).translate(-d.x, -d.y)
        )
      }
    })

    // Double clic → vue RDF détail (top concept et tous types)
    nodeMerged.on('dblclick', function(event, d) {
      event.stopPropagation()
      if (d.kind === 'literal') return
      onNodeDblClick(d.uri)
    })

    // Drag
    nodeMerged.call(
      d3.drag<SVGGElement, SimNode>()
        .on('start', (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag',  (ev, d) => { d.fx = ev.x; d.fy = ev.y })
        .on('end',   (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
    )

    // Tick (offset endpoints so arrow sits at node boundary)
    sim.on('tick', () => {
      linkMerged
        .each(function(d) {
          const src = d.source as SimNode, tgt = d.target as SimNode
          const sx = src.x ?? 0, sy = src.y ?? 0
          const tx = tgt.x ?? 0, ty = tgt.y ?? 0
          const dx = tx - sx, dy = ty - sy
          const dist = Math.sqrt(dx*dx + dy*dy) || 1
          const x1 = sx + (dx / dist) * src.r
          const y1 = sy + (dy / dist) * src.r
          const x2 = tx - (dx / dist) * (tgt.r + 8)  // 8 = arrowhead space
          const y2 = ty - (dy / dist) * (tgt.r + 8)
          d3.select(this).attr('x1', x1).attr('y1', y1).attr('x2', x2).attr('y2', y2)
        })
      lblMerged
        .attr('x', d => (((d.source as SimNode).x ?? 0) + ((d.target as SimNode).x ?? 0)) / 2)
        .attr('y', d => (((d.source as SimNode).y ?? 0) + ((d.target as SimNode).y ?? 0)) / 2 - 5)
      nodeMerged.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`)
    })

  }, [nodes, edges, selectedUri]) // eslint-disable-line react-hooks/exhaustive-deps

  // Search highlight (no sim restart)
  useEffect(() => {
    nodeLayerRef.current?.selectAll<SVGGElement, SimNode>('g.gnode')
      .classed('highlighted', d => searchHighlight.has(d.uri))
  }, [searchHighlight])

  return <svg ref={svgRef} className="graph-canvas" aria-label="Graphe SKOS" />
}
