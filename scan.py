import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, quote, unquote
from urllib.request import Request, urlopen

OUTPUT = Path("site/data.json")

# Podés agregar más páginas a esta lista.
SOURCES = [
    {
        "name": "Novedades RSS",
        "url": "https://www.jw.org/es/lo-nuevo/rss/WhatsNewWebArticles/feed.xml",
        "type": "rss",
    },
    {
        "name": "Novedades",
        "url": "https://www.jw.org/es/lo-nuevo/",
        "type": "html",
        "prefix": "/es/",
    },
    {
        "name": "Noticias",
        "url": "https://www.jw.org/es/noticias/",
        "type": "html",
        "prefix": "/es/noticias/",
    },
    {
        "name": "Revistas",
        "url": "https://www.jw.org/es/biblioteca/revistas/",
        "type": "html",
        "prefix": "/es/biblioteca/revistas/",
    },
    {
        "name": "Libros y folletos",
        "url": "https://www.jw.org/es/biblioteca/libros/",
        "type": "html",
        "prefix": "/es/biblioteca/libros/",
    },
    {
        "name": "Artículos",
        "url": "https://www.jw.org/es/biblioteca/series/",
        "type": "html",
        "prefix": "/es/biblioteca/series/",
    },
    {
        "name": "Preguntas sobre la Biblia",
        "url": "https://www.jw.org/es/enseñanzas-bíblicas/preguntas/",
        "type": "html",
        "prefix": "/es/enseñanzas-bíblicas/preguntas/",
    },
]

SOURCES.extend([
    {"name": "Mapa completo en español", "url": "https://www.jw.org/es/sitemap.xml", "type": "sitemap"},
    {"name": "Catálogo multimedia en español", "url": "https://b.jw-cdn.org/apis/mediator/v1/categories/S", "type": "media"},
])


def sitemap_items(url, visited=None):
    visited = set() if visited is None else visited
    if url in visited:
        return []
    if not canonical(url):
        raise ValueError("Mapa fuera de jw.org")
    visited.add(url)
    root = ET.fromstring(fetch(url))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.endswith("sitemapindex"):
        result = []
        for node in root.findall("s:sitemap", ns):
            result.extend(sitemap_items(node.findtext("s:loc", namespaces=ns), visited))
        return result
    if not root.tag.endswith("urlset"):
        raise ValueError("Formato de mapa desconocido")
    result = []
    for node in root.findall("s:url", ns):
        link = canonical(node.findtext("s:loc", default="", namespaces=ns))
        if link and urlsplit(link).path.startswith("/es/"):
            result.append({"url": link, "title": unquote(urlsplit(link).path).strip("/").split("/")[-1].replace("-", " "),
                           "published": None, "modified": node.findtext("s:lastmod", namespaces=ns)})
    return result


def media_items(base):
    pending = [c["key"] for c in json.loads(fetch(base + "?detailed=1"))["categories"]]
    visited, result = set(), {}
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        offset = 0
        while True:
            data = json.loads(fetch(base + "/" + quote(key, safe="") + f"?detailed=1&limit=500&offset={offset}"))
            category = data["category"]
            pending.extend(c["key"] for c in category.get("subcategories", []))
            media = category.get("media", [])
            for item in media:
                identity = item.get("languageAgnosticNaturalKey") or item.get("naturalKey")
                if not identity or not item.get("title"):
                    raise ValueError("Elemento multimedia sin identificador o título")
                link = "https://www.jw.org/es/biblioteca/videos/#es/mediaitems/" + quote(identity, safe="")
                result[link] = {"url": link, "title": item["title"], "published": item.get("firstPublished"),
                                "section": "Videos" if item.get("type") == "video" else "Audio y música"}
            pagination = data.get("pagination") or {}
            total = pagination.get("totalCount", len(media))
            offset += len(media)
            if offset >= total:
                break
            if not media:
                raise ValueError(f"Paginación incompleta: {key}, {offset}/{total}")
        time.sleep(0.05)
    return list(result.values())


def now():
    return datetime.now(timezone.utc).isoformat()

def canonical(url):
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        return None
    if p.hostname not in ("jw.org", "www.jw.org"):
        return None
    fragment = p.fragment if p.fragment.startswith("es/mediaitems/") else ""
    return urlunsplit(("https", "www.jw.org", quote(unquote(p.path), safe="/"), "", fragment))

def section(url):
    path = urlsplit(url).path
    for part, label in [
        ("/noticias/", "Noticias"),
        ("/revistas/", "Revistas"),
        ("/libros/", "Libros y folletos"),
        ("/videos/", "Videos"),
        ("/musica/", "Música"),
        ("/series/", "Artículos"),
        ("/preguntas/", "Preguntas sobre la Biblia"),
    ]:
        if part in path:
            return label
    return "Otros"

class Links(HTMLParser):
    """Lee enlaces únicamente dentro del contenido principal."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.anchor = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "main":
            self.main_depth += 1

        if self.main_depth and tag == "a":
            self.anchor = {
                "href": attrs.get("href", ""),
                "parts": [],
                "fallback": attrs.get("aria-label", ""),
            }

        if self.anchor and tag == "img":
            self.anchor["parts"].append(attrs.get("alt", ""))

    def handle_data(self, data):
        if self.anchor:
            self.anchor["parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            title = " ".join(
                " ".join(self.anchor["parts"]).split()
            ) or self.anchor["fallback"]

            self.items.append((self.anchor["href"], title))
            self.anchor = None

        if tag == "main":
            self.main_depth = max(0, self.main_depth - 1)

def fetch(url):
    parts = urlsplit(url)
    url = urlunsplit((parts.scheme, parts.netloc, quote(unquote(parts.path), safe="/"), parts.query, ""))
    request = Request(
        url,
        headers={
            "User-Agent": "JW-Publication-Monitor/1.0",
            "Accept": "text/html, application/xml, text/xml",
        },
    )
    with urlopen(request, timeout=35) as response:
        body = response.read(50_000_001)
        if len(body) > 50_000_000:
            raise ValueError("La respuesta supera el límite de 50 MB")
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")

def rss_items(text):
    root = ET.fromstring(text)
    result = []

    for item in root.findall(".//item"):
        url = canonical((item.findtext("link") or "").strip())
        title = (item.findtext("title") or "").strip()
        if url and title:
            result.append({
                "url": url,
                "title": title,
                # Se conserva tal como la informa la fuente.
                "published": item.findtext("pubDate") or None,
            })

    return result

def html_items(text, source):
    parser = Links()
    parser.feed(text)
    result = {}
    source_url = canonical(source["url"])

    for href, title in parser.items:
        url = canonical(urljoin(source["url"], href))
        if not url or url == source_url or len(title) < 5:
            continue

        path = urlsplit(url).path
        prefix = source["prefix"]

        if not path.startswith(prefix):
            continue

        # Evita enlaces a archivos descargables.
        if path.lower().endswith((".pdf", ".jpg", ".png", ".mp4", ".mp3")):
            continue

        # En Novedades excluye páginas generales de navegación.
        if source["name"] == "Novedades":
            if len(path.strip("/").split("/")) < 4:
                continue

        result[url] = {
            "url": url,
            "title": title[:600],
            "published": None,
        }

    return list(result.values())

def run():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if OUTPUT.exists():
        state = json.loads(OUTPUT.read_text(encoding="utf-8"))
    else:
        state = {
            "items": {},
            "sources": {},
            "created": now(),
        }

    # Descarta avisos de actualizaciones creados por versiones anteriores.
    state["pending_notifications"] = {
        url: event for url, event in state.get("pending_notifications", {}).items()
        if event.get("kind") == "Nuevo"
    }
    checked = now()
    successful = 0

    for source in SOURCES:
        name = source["name"]
        previous = state["sources"].get(name, {})
        baseline = not previous.get("initialized", False)

        try:
            if source["type"] == "sitemap":
                items = sitemap_items(source["url"])
            elif source["type"] == "media":
                items = media_items(source["url"])
            else:
                body = fetch(source["url"])
                items = rss_items(body) if source["type"] == "rss" else html_items(body, source)

            if not items:
                raise ValueError(
                    "No se encontraron elementos. "
                    "Puede haber cambiado la página o cargar con JavaScript."
                )

            added = 0

            for item in items:
                url = item["url"]
                existing = state["items"].get(url)

                if existing is None:
                    state["items"][url] = {
                        **item,
                        "section": item.get("section", section(url)),
                        "first_seen": checked,
                        "last_seen": checked,
                        "baseline": baseline,
                        "sources": [name],
                    }
                    if not baseline:
                        added += 1
                        state["pending_notifications"][url] = {"title": item["title"], "url": url, "kind": "Nuevo", "detected": checked, "delivered": []}
                else:
                    existing["last_seen"] = checked
                    if item.get("modified"):
                        existing["modified"] = item["modified"]
                    if source["type"] != "sitemap":
                        existing["title"] = item["title"]
                    if name not in existing["sources"]:
                        existing["sources"].append(name)
                    if item["published"]:
                        existing["published"] = item["published"]

            state["sources"][name] = {
                "url": source["url"],
                "initialized": True,
                "status": "ok",
                "checked": checked,
                "last_success": checked,
                "count": len(items),
                "new": added,
                "error": None,
            }
            successful += 1
            print(f"OK: {name}: {len(items)} enlaces, {added} nuevos")

        except Exception as exc:
            state["sources"][name] = {
                **previous,
                "url": source["url"],
                "status": "error",
                "checked": checked,
                "error": str(exc)[:500],
            }
            print(f"ERROR: {name}: {exc}")

        time.sleep(1)

    state["checked"] = checked
    state["successful_sources"] = successful
    state["total_sources"] = len(SOURCES)

    # Escritura atómica: conserva el archivo anterior si falla la escritura.
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(OUTPUT)

if __name__ == "__main__":
    run()