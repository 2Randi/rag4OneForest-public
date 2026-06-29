import { useEffect, useMemo, useRef } from "react";
import {
  drag,
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  select,
  zoom,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3";
import { Parser } from "n3";

type NodeKind = "concept" | "scheme" | "class" | "resource";

interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  kind: NodeKind;
  degree: number;
}

interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
}

const SKOS = "http://www.w3.org/2004/02/skos/core#";
const DCT = "http://purl.org/dc/terms/";
const RDFS = "http://www.w3.org/2000/01/rdf-schema#";
const RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";

const colors: Record<NodeKind, string> = {
  concept: "#61c77f",
  scheme: "#4d8ed8",
  class: "#51b8c0",
  resource: "#d99b43",
};

const shortId = (value: string) => value.split("#").at(-1)?.replaceAll("_", " ") ?? value;

function parseGraph(turtle: string) {
  const quads = new Parser().parse(turtle);
  const nodeById = new Map<string, GraphNode>();
  const labelById = new Map<string, string>();
  const kindById = new Map<string, NodeKind>();
  const edges: GraphEdge[] = [];

  const addNode = (id: string, kind: NodeKind = "resource", label?: string) => {
    if (!nodeById.has(id)) {
      nodeById.set(id, { id, label: label ?? shortId(id), kind, degree: 0 });
    }
    const node = nodeById.get(id)!;
    if (label && node.label === shortId(id)) node.label = label;
    if (kind !== node.kind && node.kind === "resource") node.kind = kind;
    return node;
  };

  const addEdge = (subject: string, object: string) => {
    if (subject === object) return;
    const sourceNode = addNode(subject, kindById.get(subject) ?? "resource");
    const targetNode = addNode(object, kindById.get(object) ?? "resource");
    sourceNode.degree += 1;
    targetNode.degree += 1;
    edges.push({ source: sourceNode.id, target: targetNode.id });
  };

  for (const quad of quads) {
    const subject = quad.subject.value;
    const predicate = quad.predicate.value;
    const object = quad.object;

    if (predicate === `${RDF}type`) {
      if (object.value === `${SKOS}Concept`) kindById.set(subject, "concept");
      if (object.value === `${SKOS}ConceptScheme`) kindById.set(subject, "scheme");
      if (object.value === `${RDFS}Class`) kindById.set(subject, "class");
    }

    if (predicate === `${SKOS}prefLabel` || predicate === `${RDFS}label`) {
      if (object.termType === "Literal") {
        labelById.set(subject, object.value);
      }
    }

    if (object.termType === "NamedNode") {
      if (
        predicate === `${SKOS}broader` ||
        predicate === `${SKOS}narrower` ||
        predicate === `${SKOS}related` ||
        predicate === `${SKOS}broadMatch` ||
        predicate === `${SKOS}narrowMatch` ||
        predicate === `${SKOS}closeMatch` ||
        predicate === `${SKOS}exactMatch` ||
        predicate === `${SKOS}inScheme`
      ) {
        addEdge(subject, object.value);
      }
    }
  }

  for (const [id, kind] of kindById.entries()) {
    addNode(id, kind, labelById.get(id));
  }

  for (const [id, label] of labelById.entries()) {
    addNode(id, kindById.get(id) ?? "resource", label);
  }

  return { nodes: [...nodeById.values()], edges };
}

export function GraphScene({ turtle }: { turtle: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const graphData = useMemo(() => parseGraph(turtle), [turtle]);

  useEffect(() => {
    const svgElement = svgRef.current;
    if (!svgElement) return;

    const width = svgElement.clientWidth;
    const height = svgElement.clientHeight;
    const graph: { nodes: GraphNode[]; edges: GraphEdge[] } = {
      nodes: graphData.nodes.map((node) => ({ ...node })),
      edges: graphData.edges.map((edge) => ({ source: String(edge.source), target: String(edge.target) })),
    };
    const svg = select(svgElement);
    const viewport = svg.select<SVGGElement>(".viewport");
    const edgeLayer = viewport.select<SVGGElement>(".edges");
    const nodeLayer = viewport.select<SVGGElement>(".nodes");
    edgeLayer.selectAll("*").remove();
    nodeLayer.selectAll("*").remove();

    svg.call(
      zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 4])
        .on("zoom", (event) => viewport.attr("transform", event.transform)),
    );

    const links = edgeLayer
      .selectAll<SVGLineElement, GraphEdge>("line")
      .data(graph.edges)
      .join("line")
      .attr("class", "edge");

    const nodes = nodeLayer
      .selectAll<SVGGElement, GraphNode>("g")
      .data(graph.nodes)
      .join("g")
      .attr("class", (node) => `graph-node ${node.kind}`);

    nodes
      .append("circle")
      .attr("r", (node) => Math.min(6 + node.degree * 0.45, 20))
      .attr("fill", (node) => colors[node.kind]);

    nodes
      .append("text")
      .attr("x", 10)
      .attr("y", 4)
      .text((node) => node.label);

    nodes.append("title").text((node) => `${node.label} · ${node.kind}`);

    const neighbors = new Map<string, Set<string>>();
    for (const edge of graph.edges) {
      const source = String(edge.source);
      const target = String(edge.target);
      if (!neighbors.has(source)) neighbors.set(source, new Set());
      if (!neighbors.has(target)) neighbors.set(target, new Set());
      neighbors.get(source)!.add(target);
      neighbors.get(target)!.add(source);
    }

    nodes
      .on("mouseenter", (_, hovered) => {
        const connected = neighbors.get(hovered.id) ?? new Set();
        nodes.classed("faded", (node) => node.id !== hovered.id && !connected.has(node.id));
        links.classed("faded", (edge) => {
          const source = (edge.source as GraphNode).id;
          const target = (edge.target as GraphNode).id;
          return source !== hovered.id && target !== hovered.id;
        });
      })
      .on("mouseleave", () => {
        nodes.classed("faded", false);
        links.classed("faded", false);
      });

    const simulation = forceSimulation(graph.nodes)
      .force("link", forceLink<GraphNode, GraphEdge>(graph.edges).id((node) => node.id).distance(80).strength(0.5))
      .force("charge", forceManyBody().strength(-135))
      .force("collision", forceCollide<GraphNode>().radius((node) => Math.min(10 + node.degree * 0.35, 20)))
      .force("center", forceCenter(width / 2, height / 2))
      .on("tick", () => {
        links
          .attr("x1", (edge) => (edge.source as GraphNode).x ?? 0)
          .attr("y1", (edge) => (edge.source as GraphNode).y ?? 0)
          .attr("x2", (edge) => (edge.target as GraphNode).x ?? 0)
          .attr("y2", (edge) => (edge.target as GraphNode).y ?? 0);
        nodes.attr("transform", (node) => `translate(${node.x ?? 0},${node.y ?? 0})`);
      });

    nodes.call(
      drag<SVGGElement, GraphNode>()
        .on("start", (event, node) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          node.fx = node.x;
          node.fy = node.y;
        })
        .on("drag", (event, node) => {
          node.fx = event.x;
          node.fy = event.y;
        })
        .on("end", (event, node) => {
          if (!event.active) simulation.alphaTarget(0);
          node.fx = null;
          node.fy = null;
        }),
    );

    return () => {
      simulation.stop();
    };
  }, [graphData]);

  return (
    <svg className="graph" ref={svgRef} aria-label="Graphe SKOS des concepts et relations">
      <g className="viewport">
        <g className="edges" />
        <g className="nodes" />
      </g>
    </svg>
  );
}
