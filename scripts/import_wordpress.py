"""Snapshot public WordPress content. Never used by the deployed website."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "content"
ASSETS = ROOT / "assets" / "media"
ORIGIN = "https://powertips.es"


def fetch(url):
    url = quote(url, safe=":/?&=%+#")
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "PowerTips-static-migration/1.0"}), timeout=90) as response:
                return response.read(), dict(response.headers)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def inventory(kind):
    items = []
    page = 1
    total = None
    while True:
        raw, headers = fetch(f"{ORIGIN}/wp-json/wp/v2/{kind}?per_page=100&page={page}&orderby=id&order=asc")
        batch = json.loads(raw)
        headers = {key.lower(): value for key, value in headers.items()}
        current_total = int(headers["x-wp-total"])
        if total is not None and total != current_total:
            raise RuntimeError(f"{kind}: API changed during import; retry the snapshot")
        total = current_total
        items.extend(batch)
        if page >= int(headers["x-wp-totalpages"]):
            break
        page += 1
    if len({item["id"] for item in items}) != len(items) or len(items) > total or (kind != "media" and len(items) != total):
        raise RuntimeError(f"{kind}: incomplete/duplicate pagination ({len(items)} != {total})")
    print(f"{kind}: {len(items)} returned / {total} API total", flush=True)
    return items, total


def save(name, value):
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def media_url(url):
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    if re.fullmatch(r"i[0-9]+\.wp\.com", parts.netloc):
        url = "https://" + parts.path.lstrip("/")
        parts = urlsplit(url)
    if parts.hostname in ("powertips.es", "www.powertips.es") and parts.path.startswith("/wp-content/uploads/"):
        return urlunsplit(("https", "powertips.es", parts.path, "", ""))
    return None


def main():
    DATA.mkdir(exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    identity = json.loads(fetch(ORIGIN + "/wp-json/")[0])
    save("site.json", {key: identity[key] for key in ("name", "description", "url", "home")})
    report = {"source": ORIGIN, "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "totals": {}, "sitemaps": {}, "excluded_sitemaps": [],
              "media_failures": [], "protected_records": [], "asset_policy": "Referenced upload src/href/poster and featured images; unused attachments and srcset variants are inventoried, not downloaded."}
    records = {}
    for kind in ("posts", "pages", "categories", "tags", "media"):
        records[kind], report["totals"][kind] = inventory(kind)
        if kind == "media":
            gap = report["totals"][kind] - len(records[kind])
            report["media_inventory"] = {
                "api_total": report["totals"][kind], "returned": len(records[kind]),
                "unavailable": gap,
                "explanation": ("Public REST pagination returns fewer attachments than X-WP-Total. All advertised pages were fetched; omitted IDs are not exposed by the public response."
                                if gap else "All advertised public media records were returned.")}
        if kind in ("posts", "pages"):
            for item in records[kind]:
                if item["status"] != "publish" or item["content"]["protected"]:
                    report["protected_records"].append({"kind": kind, "id": item["id"], "link": item["link"]})
            records[kind] = [{key: item[key] for key in
                             ("id", "date", "modified", "slug", "status", "link", "title", "content", "excerpt", "featured_media", "categories", "tags")
                             if key in item} for item in records[kind]]
        elif kind == "media":
            records[kind] = [{key: item[key] for key in
                             ("id", "date", "slug", "link", "title", "alt_text", "source_url", "media_type", "mime_type", "media_details")
                             if key in item} for item in records[kind]]
        else:
            records[kind] = [{key: item[key] for key in ("id", "count", "description", "link", "name", "slug", "parent") if key in item}
                             for item in records[kind]]
        save(kind + ".json", records[kind])
    index_raw = fetch(ORIGIN + "/wp-sitemap.xml")[0]
    (DATA / "wp-sitemap.xml").write_bytes(index_raw)
    sitemap_urls = [node.text for node in ET.fromstring(index_raw).iter() if node.tag.endswith("}loc")]
    for kind in ("post", "page"):
        urls = []
        for sitemap in sitemap_urls:
            if re.search(rf"/wp-sitemap-posts-{kind}-\d+\.xml$", sitemap):
                raw = fetch(sitemap)[0]
                (DATA / urlsplit(sitemap).path.lstrip("/")).write_bytes(raw)
                urls.extend(node.text for node in ET.fromstring(raw).iter() if node.tag.endswith("}loc"))
        api_urls = {item["link"] for item in records[{"post": "posts", "page": "pages"}[kind]]}
        if kind == "page":
            api_urls.add(ORIGIN + "/")
        missing, extra = sorted(set(urls) - api_urls), sorted(api_urls - set(urls))
        report["sitemaps"][kind] = {"count": len(urls), "missing_from_api": missing, "not_in_sitemap": extra}
        if missing or extra:
            save("migration-report.json", report)
            raise RuntimeError(f"{kind}: REST/sitemap mismatch: {missing=} {extra=}")
    report["excluded_sitemaps"] = [url for url in sitemap_urls if not re.search(r"/wp-sitemap-posts-(post|page)-\d+\.xml$", url)]
    media_by_id = {item["id"]: item for item in records["media"]}
    media_by_link = {item["link"]: item for item in records["media"]}
    urls = set()
    for kind in ("posts", "pages"):
        for item in records[kind]:
            if item["content"]["protected"]:
                continue
            soup = BeautifulSoup(item["content"]["rendered"], "html.parser")
            for tag in soup.find_all(True):
                for attr in ("src", "href", "poster", "data-src", "data-lazy-src"):
                    if tag.get(attr) and media_url(tag[attr]):
                        urls.add(media_url(tag[attr]))
                attachment = media_by_link.get(tag.get("href"))
                if attachment and media_url(attachment["source_url"]):
                    urls.add(media_url(attachment["source_url"]))
            featured = media_by_id.get(item["featured_media"])
            if featured and media_url(featured["source_url"]):
                urls.add(media_url(featured["source_url"]))
    home = fetch(ORIGIN + "/")[0]
    soup = BeautifulSoup(home, "html.parser")
    logo = soup.select_one("img.custom-logo")
    if logo and media_url(logo.get("src", "")):
        urls.add(media_url(logo["src"]))
        site = json.loads((DATA / "site.json").read_text(encoding="utf-8"))
        site["logo"] = media_url(logo["src"])
        save("site.json", site)

    def download(url):
        extension = Path(unquote(urlsplit(url).path)).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", extension):
            extension = ".bin"
        name = hashlib.sha256(url.encode()).hexdigest()[:24] + extension
        target = ASSETS / name
        try:
            if not target.exists():
                raw, headers = fetch(url)
                content_type = next((value for key, value in headers.items() if key.lower() == "content-type"), "")
                if not raw or "text/html" in content_type:
                    raise ValueError(f"Not a media response: {content_type}")
                target.write_bytes(raw)
            return url, "/assets/media/" + name, None
        except Exception as error:
            return url, None, str(error)

    mapping = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for index, (url, local, error) in enumerate(executor.map(download, sorted(urls)), 1):
            if error:
                report["media_failures"].append({"url": url, "error": error})
                print(f"MEDIA FAILURE: {url}: {error}", flush=True)
            else:
                mapping[url] = local
            if index % 50 == 0:
                print(f"assets: {index}/{len(urls)}", flush=True)
    report["assets"] = {"referenced": len(urls), "downloaded": len(mapping),
                        "bytes": sum((ROOT / path.lstrip("/")).stat().st_size for path in mapping.values())}
    report["unreferenced_media_records"] = [
        {"id": item["id"], "url": item["source_url"]}
        for item in records["media"] if media_url(item["source_url"]) not in urls]
    save("media-map.json", mapping)
    save("migration-report.json", report)
    print(json.dumps({key: report[key] for key in ("totals", "sitemaps", "assets", "media_failures")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
