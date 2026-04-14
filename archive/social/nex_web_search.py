"""
nex_web_search.py
Web search tool for NEX execution loop.
Uses DuckDuckGo (no API key required).
Returns summarised results for belief grounding.
"""
import urllib.request, urllib.parse, json, logging, re, html
from pathlib import Path

log = logging.getLogger("nex.websearch")

def _ddg_search(query: str, max_results=5) -> list:
    """DuckDuckGo instant answer API — no key needed."""
    try:
        params = urllib.parse.urlencode({
            "q": query, "format": "json",
            "no_html": "1", "skip_disambig": "1"
        })
        url = f"https://api.duckduckgo.com/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "NEX/4.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())

        results = []
        # Abstract
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", ""),
                "snippet": data["Abstract"][:300],
                "url": data.get("AbstractURL", "")
            })
        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                    "snippet": topic["Text"][:300],
                    "url": topic.get("FirstURL", "")
                })
        return results[:max_results]
    except Exception as e:
        log.debug(f"DDG search failed: {e}")
        return []

def _html_search(query: str, max_results=5) -> list:
    """Fallback: scrape DuckDuckGo HTML results."""
    try:
        params = urllib.parse.urlencode({"q": query})
        url = f"https://html.duckduckgo.com/html/?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8", errors="ignore")

        results = []
        # Extract result snippets
        snippets = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', content, re.DOTALL)
        titles   = re.findall(
            r'<a[^>]+class="result__a"[^>]*>(.*?)</a>', content, re.DOTALL)

        for t, s in zip(titles[:max_results], snippets[:max_results]):
            title   = html.unescape(re.sub(r'<[^>]+>', '', t)).strip()
            snippet = html.unescape(re.sub(r'<[^>]+>', '', s)).strip()
            if title and snippet:
                results.append({"title": title, "snippet": snippet[:300], "url": ""})

        return results
    except Exception as e:
        log.debug(f"HTML search failed: {e}")
        return []

def search(query: str, max_results=5) -> str:
    """
    Main search function. Returns formatted string for LLM context.
    Tries DDG API first, falls back to HTML scrape.
    """
    results = _ddg_search(query, max_results)
    if not results:
        results = _html_search(query, max_results)

    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}: {r['snippet']}")

    return "\n".join(lines)

def search_and_extract_beliefs(query: str, topic: str = "") -> list:
    """
    Search and format results as belief candidates.
    Returns list of (content, confidence) tuples for DB insertion.
    """
    results = _ddg_search(query, max_results=10)
    if not results:
        results = _html_search(query, max_results=10)

    beliefs = []
    for r in results:
        snippet = r.get("snippet", "").strip()
        if len(snippet.split()) >= 8:  # at least 8 words
            beliefs.append((snippet[:200], 0.55))  # low confidence — web sourced

    return beliefs

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing web search...\n")
    result = search("consciousness hard problem qualia")
    print(result)
    print("\nBelief candidates:")
    beliefs = search_and_extract_beliefs("AI alignment safety")
    for b, c in beliefs[:3]:
        print(f"  [{c}] {b[:80]}")
