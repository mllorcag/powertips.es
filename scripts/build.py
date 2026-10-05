"""Build the site entirely from the committed WordPress snapshot."""
from collections import Counter, defaultdict
from datetime import datetime
import html
import json
import os
from pathlib import Path
import re
import shutil
import stat
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup, Comment
from import_wordpress import media_url

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_site"
ORIGIN = "https://powertips.es"
DYNAMIC_PATHS = {"/foros/", "/recuperar-contrasena/", "/registro-2-2/"}
ALLOWED_TAGS = {
    "p", "br", "a", "div", "aside", "span", "img", "figure", "figcaption", "strong", "b", "em", "i", "u",
    "s", "del", "ins", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section",
    "blockquote", "pre", "code", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "hr", "iframe", "video", "audio", "source", "sup", "sub", "details", "summary", "abbr"}
ATTRS = {"id", "class", "title", "alt", "href", "src", "poster", "width", "height", "colspan",
         "rowspan", "scope", "datetime", "start", "reversed", "type", "controls", "preload",
         "allow", "allowfullscreen", "referrerpolicy", "loading"}
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def remove_readonly(function, path, error):
    # OneDrive can mark copied output directories read-only on Windows.
    if os.name != "nt" or not isinstance(error, PermissionError):
        raise error
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
    function(path)


def load(name):
    return json.loads((ROOT / "content" / (name + ".json")).read_text(encoding="utf-8"))


def text(value):
    if "<" not in value:
        return " ".join(html.unescape(value).split())
    return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split())


def esc(value):
    return html.escape(str(value), quote=True)


def path_of(url):
    return urlsplit(url).path


def date_label(value):
    date = datetime.fromisoformat(value)
    return f"{date.day} de {MONTHS[date.month - 1]} de {date.year}"


def is_dynamic(path):
    return path in DYNAMIC_PATHS or path.startswith("/questions/")


def notice(message):
    return f'<aside class="notice" role="note">{message}</aside>'


class Builder:
    def __init__(self):
        self.site = load("site")
        self.posts = sorted(load("posts"), key=lambda item: (item["date"], item["id"]), reverse=True)
        self.pages = load("pages")
        self.categories = {item["id"]: item for item in load("categories")}
        self.tags = {item["id"]: item for item in load("tags")}
        self.media = {item["id"]: item for item in load("media")}
        self.assets = load("media-map")
        self.routes = {}
        self.compat = {}
        self.report = {"posts": len(self.posts), "pages": len(self.pages), "dynamic_pages": [],
                       "removed_forms": [], "unsupported_embeds": [], "unresolved_shortcodes": [],
                       "missing_assets": [], "rewritten_community_links": [], "unmapped_internal_links": []}
        self.all_original = {path_of(item["link"]) for item in self.posts + self.pages}
        self.all_original.update(path_of(term["link"]) for term in [*self.categories.values(), *self.tags.values()])
        self.all_original.add("/")
        self.internal_links = set()
        self.attachments = {path_of(item["link"]): item for item in self.media.values()}

    def asset(self, url):
        original = media_url(url)
        if original and original not in self.assets:
            self.report["missing_assets"].append(original)
        return self.assets.get(original, url)

    def featured(self, item):
        attachment = self.media.get(item.get("featured_media"))
        return self.asset(attachment["source_url"]) if attachment else ""

    def link(self, url):
        parts = urlsplit(url)
        if parts.hostname in ("powertips.es", "www.powertips.es"):
            if media_url(url):
                return self.asset(url)
            path = parts.path or "/"
            if re.match(r"/(?:forums?|topics?|members|usuarios|activity|register|login)(?:/|$)", path):
                self.report["rewritten_community_links"].append(url)
                return "/foros/"
            if path.startswith(("/wp-login.php", "/wp-admin")):
                return "/registro-2-2/"
            self.internal_links.add(path)
            return path + ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else "")
        return url

    def body(self, item):
        path = path_of(item["link"])
        if is_dynamic(path):
            self.report["dynamic_pages"].append(item["link"])
            return notice("Esta dirección pertenecía a los foros, preguntas o cuentas de PowerTips. "
                          "La versión estática conserva los artículos públicos, pero no ofrece foros, "
                          "registro, perfiles ni recuperación de contraseñas. "
                          '<a href="/archivo/">Explora el archivo de artículos</a>.')
        if item["content"]["protected"]:
            return notice("El contenido de esta página no era público y no se ha importado.")
        soup = BeautifulSoup(item["content"]["rendered"], "html.parser")
        forms = soup.find_all("form")
        if forms:
            self.report["removed_forms"].append({"url": item["link"], "count": len(forms)})
        for form in forms:
            form.replace_with(BeautifulSoup(notice("El formulario de WordPress no está disponible en esta versión estática. "
                                                  'Puedes contactar con el autor mediante <a href="https://mypublicinbox.com/mllorcag">MyPublicInbox</a>.'), "html.parser"))
        for tag in list(soup.find_all(["script", "style", "noscript", "input", "button", "textarea", "select"])):
            tag.decompose()
        for comment in soup.find_all(string=lambda node: isinstance(node, Comment)):
            comment.extract()
        for tag in list(soup.find_all(True)):
            if tag.name not in ALLOWED_TAGS:
                tag.unwrap()
                continue
            if tag.name == "iframe":
                src = tag.get("src", "")
                parts = urlsplit(src)
                if parts.hostname not in ("www.youtube.com", "www.youtube-nocookie.com", "www.linkedin.com"):
                    self.report["unsupported_embeds"].append({"url": item["link"], "src": src})
                    tag.replace_with(BeautifulSoup(notice("Este contenido incrustado no está disponible."), "html.parser"))
                    continue
                tag["title"] = tag.get("title") or ("Vídeo de YouTube" if "youtube" in parts.hostname else "Curso de LinkedIn Learning")
                tag["loading"] = "lazy"
                tag["referrerpolicy"] = "strict-origin-when-cross-origin"
                tag["allowfullscreen"] = ""
            if tag.name == "img":
                source = tag.get("data-src") or tag.get("data-lazy-src") or tag.get("src")
                if source:
                    tag["src"] = self.asset(source)
                tag["alt"] = tag.get("alt", "")
                tag["loading"] = "lazy"
            for attr in list(tag.attrs):
                if attr not in ATTRS:
                    del tag[attr]
            for attr in ("href", "src", "poster"):
                if tag.get(attr):
                    value = tag[attr].strip()
                    # Remove control characters before testing schemes.
                    scheme = urlsplit(re.sub(r"[\x00-\x20]", "", value)).scheme.lower()
                    if scheme not in ("", "http", "https", "mailto", "tel"):
                        del tag[attr]
                    else:
                        tag[attr] = self.link(value) if attr == "href" else self.asset(value)
        # All known dynamic shortcodes are replaced above; flag any new ones.
        codes = re.findall(r"\[(?:/?[a-zA-Z_][^\]\n]*)\]", soup.get_text())
        if codes:
            self.report["unresolved_shortcodes"].append({"url": item["link"], "shortcodes": codes})
            raise ValueError(f"Unresolved WordPress shortcodes: {item['link']}: {codes}")
        body = str(soup)
        if not text(body):
            body = notice("Esta página no contenía texto público en el archivo de WordPress.")
        return body

    def frame(self, title, description, path, content, image="", article=None, noindex=False):
        canonical = ORIGIN + path
        page_title = title if title == self.site["name"] else f'{title} | {self.site["name"]}'
        logo = self.assets.get(self.site.get("logo"), "")
        structured = ""
        if article:
            data = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": title,
                    "datePublished": article["date"], "dateModified": article["modified"],
                    "mainEntityOfPage": canonical, "publisher": {"@type": "Organization", "name": self.site["name"]}}
            if image:
                data["image"] = ORIGIN + image if image.startswith("/") else image
            structured = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + "</script>"
        ogimage = f'<meta property="og:image" content="{esc(ORIGIN + image if image.startswith("/") else image)}">' if image else ""
        return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page_title)}</title>
<meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(canonical)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}"><meta property="og:locale" content="es_ES">
<meta property="og:type" content="{'article' if article else 'website'}">{ogimage}
<meta name="twitter:card" content="summary_large_image">
{'<meta name="robots" content="noindex,follow">' if noindex else ''}
<meta name="theme-color" content="#12263a"><link rel="stylesheet" href="/assets/site.css">
{f'<link rel="icon" href="{esc(logo)}">' if logo else ''}
<link rel="alternate" type="application/rss+xml" title="PowerTips.es" href="/feed/index.xml">
<script src="/assets/site.js" defer></script>{structured}</head>
<body><a class="skip-link" href="#contenido">Saltar al contenido</a>
<header class="site-header"><div class="container header-inner"><a class="brand" href="/" aria-label="PowerTips.es — inicio">
{f'<img src="{esc(logo)}" width="112" height="44" alt="">' if logo else ''}<span>PowerTips<span class="brand-dot">.es</span></span></a>
<nav aria-label="Principal"><a href="/archivo/">Artículos</a><a href="/categorias/">Temas</a><a href="/acerca-de/">Acerca de</a><a href="/meetup/">Comunidad</a><a href="/buscar/">Buscar</a></nav></div></header>
<main id="contenido" class="container">{content}</main>
<footer><div class="container"><strong>{esc(self.site["name"])}</strong><p>{esc(self.site["description"])}</p>
<p>Archivo público · Sin cuentas, formularios ni comentarios de WordPress.</p>
<nav aria-label="Pie de página"><a href="/colaborar/">Colaborar</a><a href="/archivo/">Archivo</a><a href="/feed/index.xml">RSS</a><a href="https://www.youtube.com/@PowerTipsES">YouTube</a><a href="https://mypublicinbox.com/mllorcag">Contacto externo</a></nav></div></footer></body></html>"""

    def write(self, path, title, content, description=None, image="", article=None, noindex=False):
        decoded = unquote(path)
        if not path.startswith("/") or not path.endswith("/") or ".." in decoded.split("/") or "\\" in decoded:
            raise ValueError(f"Unsafe/non-directory route: {path}")
        if decoded.casefold() in {unquote(route).casefold() for route in self.routes}:
            raise ValueError(f"Duplicate route: {path}")
        target = OUT / decoded.lstrip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.frame(title, description or self.site["description"], path, content, image, article, noindex), encoding="utf-8")
        self.routes[path] = {"title": title, "noindex": noindex, "modified": article["modified"][:10] if article else None}

    def chips(self, item, taxonomy="categories"):
        lookup = self.categories if taxonomy == "categories" else self.tags
        return "".join(f'<a class="chip" href="{esc(path_of(lookup[term]["link"]))}">{esc(lookup[term]["name"])}</a>'
                       for term in item.get(taxonomy, []) if term in lookup)

    def card(self, item):
        image = self.featured(item)
        title = text(item["title"]["rendered"])
        return f"""<article class="card"><a class="card-image" href="{esc(path_of(item["link"]))}" tabindex="-1" aria-hidden="true">
{f'<img src="{esc(image)}" alt="" width="640" height="360" loading="lazy">' if image else '<span class="image-placeholder">PowerTips</span>'}</a>
<div class="card-body"><time datetime="{esc(item["date"][:10])}">{date_label(item["date"])}</time>
<h2><a href="{esc(path_of(item["link"]))}">{esc(title)}</a></h2><p>{esc(text(item["excerpt"]["rendered"])[:190])}</p>
<div class="chips">{self.chips(item)}</div></div></article>"""

    def grid(self, items):
        return '<div class="grid">' + "".join(self.card(item) for item in items) + "</div>"

    def build(self):
        if OUT.exists():
            shutil.rmtree(OUT, onexc=remove_readonly)
        OUT.mkdir()
        shutil.copytree(ROOT / "assets", OUT / "assets")
        shutil.copyfile(ROOT / "CNAME", OUT / "CNAME")
        (OUT / ".nojekyll").touch()
        for item in self.posts + self.pages:
            path = path_of(item["link"])
            title = text(item["title"]["rendered"])
            body = self.body(item)
            is_post = item in self.posts
            image = self.featured(item)
            header = f'<div class="article-heading"><a class="back-link" href="/archivo/">← Archivo de artículos</a><h1>{esc(title)}</h1>'
            if is_post:
                header += f'<time datetime="{item["date"][:10]}">{date_label(item["date"])}</time><div class="chips">{self.chips(item)}</div>'
            header += "</div>"
            footer = '<div class="article-tags"><h2>Etiquetas</h2><div class="chips">' + self.chips(item, "tags") + "</div></div>" if item.get("tags") else ""
            if is_post:
                footer += notice("Los comentarios de WordPress no están disponibles en esta versión estática. "
                                 "Los enlaces a YouTube y otros recursos externos siguen disponibles.")
            content = f'<article class="reading">{header}<div class="article-body">{body}</div>{footer}</article>'
            self.write(path, title, content, text(item["excerpt"]["rendered"] or body)[:160],
                       image, item if is_post else None, noindex=is_dynamic(path))
            self.compat[str(item["id"])] = path
        attachment_routes = sorted(self.internal_links & self.attachments.keys())
        for path in attachment_routes:
            item = self.attachments[path]
            source = self.asset(item["source_url"])
            title = text(item["title"]["rendered"]) or "Imagen del archivo"
            content = f'<article class="reading"><h1>{esc(title)}</h1><div class="article-body"><figure><a href="{esc(source)}"><img src="{esc(source)}" alt="{esc(item.get("alt_text", ""))}"></a></figure></div><a href="/archivo/">Volver al archivo</a></article>'
            self.write(path, title, content, image=source)
            self.compat[str(item["id"])] = path
        self.report["attachment_routes"] = attachment_routes
        total = len(self.posts)
        years = sorted({post["date"][:4] for post in self.posts}, reverse=True)
        hero = f"""<section class="hero"><p class="eyebrow">Tecnología que impulsa tu trabajo</p>
<h1>{esc(self.site['name'])}</h1><p class="tagline">{esc(self.site['description'])}</p>
<p>Ideas, guías y vídeos para aprender, compartir y trabajar mejor con la tecnología de Microsoft.</p>
<div class="hero-actions"><a class="button" href="/archivo/">Explorar {total} artículos</a><a class="button secondary" href="/categorias/">Descubrir temas</a></div>
<p class="archive-info">Archivo publicado · {years[-1]}–{years[0]}</p></section>"""
        self.write("/", self.site["name"], hero + '<section class="section-heading"><h2>Últimos artículos</h2><a href="/archivo/">Ver todo el archivo →</a></section>' + self.grid(self.posts[:12]))
        archive = '<h1>Archivo de artículos</h1><p>Todos los artículos publicados, ordenados por fecha.</p><nav class="year-nav" aria-label="Años del archivo">'
        archive += "".join(f'<a href="#year-{year}">{year}</a>' for year in years) + "</nav>"
        for year in years:
            posts = [item for item in self.posts if item["date"].startswith(year)]
            archive += f'<section><h2 id="year-{year}">{year} <small>({len(posts)} artículos)</small></h2><ol class="archive-list">'
            archive += "".join(f'<li><time datetime="{item["date"][:10]}">{date_label(item["date"])}</time><a href="{esc(path_of(item["link"]))}">{esc(text(item["title"]["rendered"]))}</a></li>' for item in posts)
            archive += "</ol></section>"
        self.write("/archivo/", "Archivo de artículos", archive, f"Los {total} artículos de PowerTips.es sobre Power Platform, Dynamics 365 y Modern Work.")
        for taxonomy, lookup in (("categories", self.categories), ("tags", self.tags)):
            for term in lookup.values():
                posts = [item for item in self.posts if term["id"] in item[taxonomy]]
                content = f'<h1>{esc(term["name"])}</h1><p>{len(posts)} artículos</p>'
                if term["description"]:
                    content += f'<p>{esc(text(term["description"]))}</p>'
                content += self.grid(posts) if posts else "<p>No hay artículos públicos en este tema.</p>"
                self.write(path_of(term["link"]), term["name"], content)
        topics = sorted(self.categories.values(), key=lambda item: (-item["count"], item["name"]))
        self.write("/categorias/", "Temas", '<h1>Explora por temas</h1><p>Encuentra contenidos según la tecnología que te interesa.</p><ul class="topic-list">' +
                   "".join(f'<li><a href="{esc(path_of(term["link"]))}">{esc(term["name"])} <span>{term["count"]} artículos</span></a></li>' for term in topics) + "</ul>")
        dates = defaultdict(list)
        for post in self.posts:
            dates["/" + post["date"][:4] + "/"].append(post)
            dates["/" + post["date"][:7].replace("-", "/") + "/"].append(post)
        for path, posts in dates.items():
            label = path.strip("/").replace("/", " · ")
            self.write(path, f"Archivo {label}", f'<h1>Archivo {esc(label)}</h1>' + self.grid(posts))
        self.write("/buscar/", "Buscar en PowerTips", """<div class="search-page"><h1>Buscar en PowerTips</h1>
<p>Busca en títulos, textos, categorías y etiquetas de todos los artículos publicados.</p>
<form id="search-form" role="search"><label for="search-input">¿Qué quieres aprender?</label><div class="search-controls">
<input type="search" id="search-input" name="q" placeholder="Power BI, Teams, Business Central…" autocomplete="off"><button class="button" type="submit">Buscar</button></div></form>
<p id="search-status" role="status" aria-live="polite"></p><ul id="search-results" class="search-results"></ul>
<noscript><p>La búsqueda necesita JavaScript; el <a href="/archivo/">archivo completo</a> y los <a href="/categorias/">temas</a> funcionan sin él.</p></noscript></div>""", noindex=True)
        search = [{"title": text(item["title"]["rendered"]), "url": path_of(item["link"]), "date": date_label(item["date"]),
                   "text": text(item["content"]["rendered"]),
                   "topics": [self.categories[i]["name"] for i in item["categories"]] + [self.tags[i]["name"] for i in item["tags"]]}
                  for item in self.posts if not item["content"]["protected"]]
        (OUT / "search-index.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        self.write_compat()
        (OUT / "404.html").write_text(self.frame("Página no encontrada", "Esta dirección no está disponible en el archivo estático.", "/404.html",
            '<div class="not-found"><h1>Página no encontrada</h1><p>Esta dirección puede pertenecer a una antigua función de WordPress que no se conserva, como los foros o las cuentas.</p><a class="button" href="/archivo/">Ir al archivo</a><p><a href="/">Volver al inicio</a></p></div>', noindex=True), encoding="utf-8")
        self.write_xml()
        for link in self.internal_links:
            if link not in self.routes and not link.startswith("/assets/"):
                self.report["unmapped_internal_links"].append(link)
        for key in ("missing_assets", "rewritten_community_links", "unmapped_internal_links"):
            self.report[key] = sorted(set(self.report[key]))
        self.report["generated_routes"] = len(self.routes)
        (OUT / "build-report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(self.report, ensure_ascii=False, indent=2))

    def write_compat(self):
        data = {"ids": self.compat, "categories": {str(term["id"]): path_of(term["link"]) for term in self.categories.values()},
                "routes": list(self.routes)}
        (OUT / "compatibility.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def write_xml(self):
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        ET.register_namespace("", namespace)
        sitemap = ET.Element(f"{{{namespace}}}urlset")
        for path, info in self.routes.items():
            if info["noindex"]:
                continue
            node = ET.SubElement(sitemap, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = ORIGIN + path
            if info["modified"]:
                ET.SubElement(node, f"{{{namespace}}}lastmod").text = info["modified"]
        ET.ElementTree(sitemap).write(OUT / "sitemap.xml", encoding="utf-8", xml_declaration=True)
        (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /buscar/\nSitemap: https://powertips.es/sitemap.xml\n", encoding="utf-8")
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        for key, value in (("title", self.site["name"]), ("link", ORIGIN + "/"), ("description", self.site["description"]), ("language", "es")):
            ET.SubElement(channel, key).text = value
        for post in self.posts[:20]:
            node = ET.SubElement(channel, "item")
            for key, value in (("title", text(post["title"]["rendered"])), ("link", post["link"]), ("guid", post["link"]), ("description", text(post["excerpt"]["rendered"]))):
                ET.SubElement(node, key).text = value
        feed = OUT / "feed"
        feed.mkdir()
        ET.ElementTree(rss).write(feed / "index.xml", encoding="utf-8", xml_declaration=True)
        # Pages serves index.html at directory routes; the feed's canonical URL is the explicit XML file.
        (feed / "index.html").write_text(self.frame("RSS", self.site["description"], "/feed/", '<h1>RSS de PowerTips</h1><p><a href="/feed/index.xml">Suscribirse al feed XML</a></p>'), encoding="utf-8")


if __name__ == "__main__":
    Builder().build()
