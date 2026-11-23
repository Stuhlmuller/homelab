/**
 * Node sphere colors, keyed by draw order. Saturated enough to hold their hue as
 * lit 3D spheres (pale pastels blow out to white under the scene lighting); the
 * legend swatches reuse these same values.
 */
export const PALETTE = [
    "#4FA8F0",
    "#B6DE3E",
    "#D96FA6",
    "#A97FE0",
    "#D98A6B",
    "#3FBFA0",
    "#E0A63E",
    "#6E8FF0",
];
/**
 * HTML-escape the five characters that could break out of text or an attribute
 * value, so wiki-sourced strings are safe to assign to innerHTML.
 */
const HTML_ESCAPES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
};
/**
 * Escape the HTML-significant characters in a string before it is inserted into
 * the DOM. This is the sole XSS gate for wiki-sourced text.
 */
export function escapeHtml(value) {
    return value.replace(/[&<>"]/g, (char) => HTML_ESCAPES[char] ?? char);
}
/**
 * Map each distinct node type to a palette color by its position in the list, so
 * the graph and legend agree on colors and they stay stable across reloads.
 */
export function colorsForTypes(types, palette = PALETTE) {
    const colors = {};
    types.forEach((type, i) => {
        colors[type] = palette[i % palette.length];
    });
    return colors;
}
/**
 * Convert a `#RRGGBB` hex color plus an alpha into an `rgba(...)` string, for
 * canvas glow fills and dimming. A non-6-digit input is returned unchanged.
 */
export function hexA(hex, alpha) {
    const c = (hex || "").replace("#", "");
    if (c.length !== 6)
        return hex;
    const channel = (i) => parseInt(c.slice(i, i + 2), 16);
    return `rgba(${channel(0)}, ${channel(2)}, ${channel(4)}, ${alpha})`;
}
/**
 * Node circle radius in graph units, scaled by page length and capped, with a
 * bonus for the entry (anchor) page so it reads as the starting point.
 */
export function nodeRadius(size, isAnchor) {
    return 4 + Math.min(7, (size || 0) / 480) + (isAnchor ? 4 : 0);
}
/**
 * Keep graph labels contextual: hover reveals only the hovered node, while a
 * selected node reveals itself plus its immediate neighbours.
 */
export function shouldShowNodeLabel(node, context) {
    if (context.selectedId) {
        return node.id === context.selectedId || context.isInSelectedNeighborhood;
    }
    return node.id === context.hoveredId;
}
/**
 * Whether a node survives the active search text and type filter. An empty query
 * or empty type matches everything.
 */
export function matchesFilter(node, query, type) {
    const haystack = `${node.title} ${node.id} ${(node.tags ?? []).join(" ")}`;
    const matchesQuery = !query || haystack.toLowerCase().includes(query);
    const matchesType = !type || node.type === type;
    return matchesQuery && matchesType;
}
/**
 * A stable fingerprint of the graph's topology (its node ids and directed edges).
 * When it is unchanged across a reload, the scene can be left untouched so the
 * layout and viewport do not snap.
 */
export function signature(graph) {
    const nodes = graph.nodes
        .map((node) => node.id)
        .sort()
        .join("|");
    const edges = graph.edges
        .map((edge) => `${edge.source}>${edge.target}`)
        .sort()
        .join("|");
    return `${nodes}::${edges}`;
}
/**
 * Strip a leading YAML frontmatter block from a markdown body before it is
 * rendered in the reader. A body without frontmatter is returned unchanged.
 */
export function stripFrontmatter(body) {
    if (!body.startsWith("---"))
        return body;
    const end = body.indexOf("\n---", 3);
    return end === -1 ? body : body.slice(body.indexOf("\n", end + 1) + 1);
}
const REPOSITORY_FILES = "https://github.com/Stuhlmuller/homelab/blob/main/";
const WIKI_FILES = REPOSITORY_FILES + "openwiki/";

export function readerLink(page, href) {
    // Preserve explicit external links and existing host-root paths.
    if (!href || /^(?:[a-z][a-z0-9+.-]*:|[\\/])/i.test(href))
        return null;
    const source = page.split("/").map(encodeURIComponent).join("/");
    const url = new URL(href, WIKI_FILES + source + ".md");
    if (!url.href.startsWith(REPOSITORY_FILES))
        return null;
    const isWikiPage = url.href.startsWith(WIKI_FILES) && url.pathname.endsWith(".md");
    try {
        const id = isWikiPage ? decodeURIComponent(url.href.slice(WIKI_FILES.length).split(/[?#]/, 1)[0].slice(0, -3)) : null;
        return { url: url.href, id, fragment: decodeURIComponent(url.hash.slice(1)) };
    } catch {
        return null;
    }
}

export function findHeading(headings, fragment) {
    const seen = new Set();
    return Array.from(headings).find((heading) => {
        const base = heading.textContent.trim().toLowerCase()
            .replace(/[^\p{L}\p{N}_\s-]/gu, "").replace(/\s/g, "-");
        let slug = base;
        for (let number = 1; seen.has(slug); number++)
            slug = `${base}-${number}`;
        seen.add(slug);
        return slug === fragment;
    });
}
