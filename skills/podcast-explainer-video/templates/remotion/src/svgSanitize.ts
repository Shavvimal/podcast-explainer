// Render-time check for SVG files inserted as markup (DiagramScene props.svg). Second layer after
// build_manifest.py svg_problems(): an allowlist of SVG shape, text and paint-server elements and
// attributes. Anything else fails the render with the file name and every problem (fail loudly):
// no <script>, no foreignObject or other HTML, no on* event attributes, no href/src that leaves the
// file, no url() other than url(#id), no DOCTYPE or ENTITY.
// CSS (N07): CSS escapes (\72, \69) are decoded before any check, and any escape at all fails.
// A <style> element must be plain rules `selectors { declarations }`: no at-rule (@import, @font-face,
// @media ...), no comment tricks, no !important. Each selector is limited to element, #id, .class,
// [attr], :pseudo and combinators, its element names must be SVG elements (no div, body, html),
// and it is rewritten under the diagram's scope id, so it can never reach the rest of the composition. Declarations in <style> and in style="" attributes keep only
// the SVG paint and text properties in CSS_PROPERTIES; anything else is dropped.
// Mermaid: export with htmlLabels false, so labels are <text>, not foreignObject.
// scripts/build_manifest.py svg_problems() mirrors these rules: change both together.

const ALLOWED_ELEMENTS = new Set(
  [
    "svg", "g", "defs", "title", "desc", "metadata", "symbol", "use", "switch",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "marker", "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask",
    "filter", "feGaussianBlur", "feOffset", "feBlend", "feFlood", "feComposite", "feMerge", "feMergeNode",
    "feColorMatrix", "feDropShadow", "feMorphology",
    "style",
  ].map((s) => s.toLowerCase()),
);

// Metadata children (rdf, dc, cc, sodipodi, inkscape) carry no rendering; they are dropped.
const DROP_SUBTREE = new Set(["metadata", "sodipodi:namedview"]);

// CSS properties kept in <style> rules and style="" attributes. Everything else is removed.
export const CSS_PROPERTIES = new Set([
  "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray",
  "stroke-dashoffset", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "opacity", "color",
  "font", "font-family", "font-size", "font-weight", "font-style", "font-variant", "letter-spacing",
  "word-spacing", "text-anchor", "dominant-baseline", "alignment-baseline", "baseline-shift",
  "text-decoration", "white-space", "paint-order", "stop-color", "stop-opacity", "marker", "marker-start",
  "marker-mid", "marker-end", "visibility", "display", "clip-path", "clip-rule", "mask", "filter",
  "flood-color", "flood-opacity", "lighting-color", "vector-effect", "shape-rendering", "text-rendering",
  "line-height", "transform", "transform-origin", "transform-box",
]);

const URL_RE = /url\(\s*(['"]?)([^)'"]*)\1\s*\)/gi;
const BAD_TEXT = [
  { re: /javascript:/i, why: "a javascript: URL" },
  { re: /@import/i, why: "an @import" },
  { re: /expression\s*\(/i, why: "a CSS expression()" },
  { re: /-moz-binding|behavior\s*:/i, why: "a CSS binding" },
];
// One selector: element names, #id, .class, [attr] or [attr="v"], :pseudo or ::pseudo(...),
// *, and the combinators space > + ~. No escapes, no url, no quotes beyond attribute values.
const SELECTOR_RE = /^(?:[a-zA-Z*][\w-]*|#[\w-]+|\.[\w-]+|\[[\w-]+(?:[~|^$*]?=(?:"[^"\\<>]*"|'[^'\\<>]*'|[\w-]+))?\]|::?[\w-]+(?:\([\w\s+-]*\))?|\s*[>+~]\s*|\s+)+$/;

// CSS escapes: \ followed by 1-6 hex digits and an optional space, or \ and any other character.
export const decodeCssEscapes = (css: string): string =>
  css.replace(/\\([0-9a-fA-F]{1,6})\s?|\\([^\n0-9a-fA-F])/g, (_, hex: string | undefined, ch: string | undefined) =>
    hex ? String.fromCodePoint(Math.min(parseInt(hex, 16), 0x10ffff) || 0xfffd) : (ch ?? ""),
  );

const badUrls = (value: string): string[] => {
  const out: string[] = [];
  for (const m of value.matchAll(URL_RE)) {
    if (!m[2].trim().startsWith("#")) out.push(`url(${m[2].trim()})`);
  }
  return out;
};

// Checks on any CSS-bearing text (a <style> body, a style="" value, any attribute value: SVG
// presentation attributes are parsed as CSS). Escapes are decoded first, then rejected.
const cssProblems = (raw: string, where: string): string[] => {
  const out: string[] = [];
  const decoded = decodeCssEscapes(raw);
  if (decoded !== raw) out.push(`a CSS escape sequence in ${where} (decoded: ${decoded.slice(0, 60)})`);
  for (const text of [raw, decoded]) {
    for (const u of badUrls(text)) out.push(`${u} in ${where}`);
    for (const b of BAD_TEXT) if (b.re.test(text)) out.push(`${b.why} in ${where}`);
  }
  // Any url( left after removing url(#id), and any other loading function, is refused too.
  const rest = decoded.replace(/url\(\s*(['"]?)#[^)'"]*\1\s*\)/gi, "");
  if (/url\s*\(|image-set\s*\(|(^|[^\w-])src\s*\(/i.test(rest) && out.length === 0) out.push(`an external reference in ${where}`);
  return out;
};

// Keep only allowlisted declarations; returns the cleaned declaration list.
const cleanDeclarations = (body: string, where: string, problems: string[]): string => {
  const kept: string[] = [];
  for (const decl of body.split(";")) {
    const d = decl.trim();
    if (!d) continue;
    const i = d.indexOf(":");
    if (i <= 0) {
      problems.push(`a malformed CSS declaration "${d.slice(0, 40)}" in ${where}`);
      continue;
    }
    const prop = d.slice(0, i).trim().toLowerCase();
    let value = d.slice(i + 1).trim();
    if (/!\s*important/i.test(value)) value = value.replace(/!\s*important/gi, "").trim();
    if (!CSS_PROPERTIES.has(prop)) continue; // dropped: not an SVG paint or text property
    kept.push(`${prop}: ${value}`);
  }
  return kept.join("; ");
};

// Parse a <style> body into plain rules, scope every selector under #scope, keep allowlisted
// declarations. Returns the rewritten CSS.
export const scopeStylesheet = (css: string, scope: string, problems: string[]): string => {
  const where = "a <style> element";
  problems.push(...cssProblems(css, where));
  const noComments = css.replace(/\/\*[^]*?\*\//g, " ");
  if (/\/\*|\*\//.test(noComments)) problems.push(`an unterminated CSS comment in ${where}`);
  if (/@/.test(noComments)) problems.push(`an at-rule (@...) in ${where}`);
  if (/<|<\/|-->|<!--/.test(noComments.replace(/<!--|-->/g, ""))) problems.push(`markup inside ${where}`);
  const out: string[] = [];
  const ruleRe = /([^{}]+)\{([^{}]*)\}/g;
  for (const m of noComments.matchAll(ruleRe)) {
    const selectors = m[1].replace(/<!--|-->/g, "").split(",").map((x) => x.trim()).filter(Boolean);
    const scoped: string[] = [];
    for (const sel of selectors) {
      if (!SELECTOR_RE.test(sel)) {
        problems.push(`an unsupported CSS selector "${sel.slice(0, 50)}" in ${where}`);
        continue;
      }
      // Element names in a selector must be SVG elements: "div", "body" or "html" could only aim
      // at the page around the diagram.
      const foreign = [...sel.replace(/\[[^\]]*\]|\([^)]*\)/g, "").matchAll(/(?:^|[\s>+~])([a-zA-Z][\w-]*)/g)]
        .map((m) => m[1].toLowerCase())
        .filter((n) => !ALLOWED_ELEMENTS.has(n));
      if (foreign.length) {
        problems.push(`a selector for non-SVG elements (${foreign.join(", ")}) in ${where}`);
        continue;
      }
      scoped.push(`#${scope} ${sel}`); // the diagram's <svg> sits inside #scope, so "svg ..." still matches
    }
    const decls = cleanDeclarations(m[2], where, problems);
    if (scoped.length && decls) out.push(`${scoped.join(", ")} { ${decls} }`);
  }
  const leftover = noComments.replace(ruleRe, "").replace(/<!--|-->/g, "").trim();
  if (leftover) problems.push(`CSS that is not a plain rule ("${leftover.slice(0, 40)}") in ${where}`);
  return out.join("\n");
};

export class UnsafeSvgError extends Error {}

// `scope` is the id of the element that wraps the inserted markup (DiagramScene's div); every
// <style> selector is rewritten under it.
export const sanitizeSvg = (markup: string, src: string, scope = "pe-diagram"): string => {
  const problems: string[] = [];
  if (/<!DOCTYPE|<!ENTITY/i.test(markup)) problems.push("a DOCTYPE or ENTITY declaration");
  const doc = new DOMParser().parseFromString(markup, "image/svg+xml");
  const root = doc.documentElement;
  if (doc.getElementsByTagName("parsererror").length > 0 || !root || root.localName.toLowerCase() !== "svg") {
    throw new UnsafeSvgError(`Diagram ${src} is not a well-formed SVG file (the root element must be <svg>).`);
  }
  const walk = (el: Element) => {
    const name = el.localName.toLowerCase();
    const tag = el.tagName.toLowerCase();
    // Metadata and namespaced editor elements (inkscape:*, sodipodi:*) never render: drop them.
    if (DROP_SUBTREE.has(name) || DROP_SUBTREE.has(tag) || tag.includes(":")) {
      el.remove();
      return;
    }
    if (!ALLOWED_ELEMENTS.has(name)) {
      problems.push(`a <${el.localName}> element`);
      return;
    }
    for (const attr of Array.from(el.attributes)) {
      const an = attr.name.toLowerCase();
      const v = attr.value;
      const where = `${attr.name} on <${el.localName}>`;
      if (an.startsWith("on")) {
        problems.push(`an event attribute ${where}`);
        continue;
      }
      if (an === "href" || an === "xlink:href" || an === "src") {
        if (!v.trim().startsWith("#")) problems.push(`${attr.name}="${v.slice(0, 60)}" on <${el.localName}> (only #id links are allowed)`);
        continue;
      }
      if (an.includes(":") && !an.startsWith("xml") && !an.startsWith("xlink:")) {
        el.removeAttribute(attr.name); // editor attributes (inkscape:label, sodipodi:...)
        continue;
      }
      problems.push(...cssProblems(v, where));
      if (an === "style") {
        const cleaned = cleanDeclarations(decodeCssEscapes(v), where, problems);
        if (cleaned) el.setAttribute("style", cleaned);
        else el.removeAttribute("style");
      }
    }
    if (name === "style") {
      if (el.children.length > 0) problems.push("markup inside a <style> element");
      el.textContent = scopeStylesheet(el.textContent ?? "", scope, problems);
      for (const a of Array.from(el.attributes)) if (a.name.toLowerCase() !== "type") el.removeAttribute(a.name);
      return;
    }
    for (const child of Array.from(el.children)) walk(child);
  };
  walk(root);
  if (problems.length > 0) {
    const uniq = [...new Set(problems)];
    throw new UnsafeSvgError(
      `Diagram ${src} is not safe to insert: it contains ${uniq.slice(0, 8).join("; ")}${uniq.length > 8 ? ` and ${uniq.length - 8} more` : ""}. ` +
        `Only SVG shapes, text, gradients, markers, url(#id) references and plain scoped CSS rules are allowed. Remove them (Mermaid: htmlLabels false) and rebuild.`,
    );
  }
  return new XMLSerializer().serializeToString(root);
};
