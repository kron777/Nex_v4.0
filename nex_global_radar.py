#!/usr/bin/env python3
"""
nex_global_radar.py
Global AGI research radar — finds research centers, pulls papers, translates, scores.
Runs nightly. Feeds nex_papers DB.
"""
import sqlite3, json, time, requests, os, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

GROQ_KEY = os.environ.get("GROQ_API_KEY","")
DB       = '/media/rr/NEX/nex_core/nex.db'

# Global research centers by region
RESEARCH_CENTERS = {
    # North America
    "OpenAI":           {"country":"US", "arxiv_search":"openai GPT AGI alignment"},
    "Anthropic":        {"country":"US", "arxiv_search":"anthropic claude constitutional AI"},
    "DeepMind":         {"country":"UK", "arxiv_search":"deepmind AGI reinforcement learning"},
    "Google Brain":     {"country":"US", "arxiv_search":"google brain neural architecture"},
    "MIT CSAIL":        {"country":"US", "arxiv_search":"MIT cognitive architecture intelligence"},
    "Stanford HAI":     {"country":"US", "arxiv_search":"stanford human AI intelligence"},
    "Berkeley BAIR":    {"country":"US", "arxiv_search":"berkeley artificial intelligence reasoning"},
    "CMU AI":           {"country":"US", "arxiv_search":"carnegie mellon cognitive systems"},
    "Allen AI":         {"country":"US", "arxiv_search":"allen institute AI reasoning commonsense"},
    "MILA Montreal":    {"country":"CA", "arxiv_search":"mila montreal deep learning Bengio"},

    # Europe
    "DeepMind London":  {"country":"UK", "arxiv_search":"deepmind london neuroscience AI"},
    "Oxford FHI":       {"country":"UK", "arxiv_search":"oxford future humanity AGI safety"},
    "Cambridge AI":     {"country":"UK", "arxiv_search":"cambridge leverhulme AI consciousness"},
    "ETH Zurich":       {"country":"CH", "arxiv_search":"ETH zurich neural learning robotics"},
    "Max Planck AI":    {"country":"DE", "arxiv_search":"max planck intelligence systems"},
    "INRIA France":     {"country":"FR", "arxiv_search":"INRIA artificial intelligence cognition"},
    "Amsterdam AI":     {"country":"NL", "arxiv_search":"amsterdam machine learning reasoning"},

    # East Asia
    "RIKEN Japan":      {"country":"JP", "arxiv_search":"RIKEN brain intelligence Japan"},
    "NTT Research JP":  {"country":"JP", "arxiv_search":"NTT research intelligence Japan"},
    "KAIST Korea":      {"country":"KR", "arxiv_search":"KAIST artificial intelligence Korea"},
    "NAVER AI Korea":   {"country":"KR", "arxiv_search":"NAVER HyperCLOVA language Korea"},
    "Tsinghua AI":      {"country":"CN", "arxiv_search":"tsinghua artificial intelligence China"},
    "Peking Univ AI":   {"country":"CN", "arxiv_search":"peking university deep learning"},
    "BAIDU Research":   {"country":"CN", "arxiv_search":"baidu ERNIE language model China"},
    "Alibaba DAMO":     {"country":"CN", "arxiv_search":"alibaba DAMO intelligence"},
    "NUS Singapore":    {"country":"SG", "arxiv_search":"NUS singapore AI reasoning"},
    "A*STAR Singapore": {"country":"SG", "arxiv_search":"ASTAR singapore neural cognitive"},
    "Academia Sinica":  {"country":"TW", "arxiv_search":"academia sinica taiwan intelligence"},

    # Middle East / Africa / Other
    "MBZUAI UAE":       {"country":"AE", "arxiv_search":"MBZUAI abu dhabi AI language"},
    "Technion Israel":  {"country":"IL", "arxiv_search":"technion israel machine learning"},
    "IIT India":        {"country":"IN", "arxiv_search":"IIT india artificial intelligence"},
    "Yandex Russia":    {"country":"RU", "arxiv_search":"yandex research language model"},
    "Samsung Research": {"country":"KR", "arxiv_search":"samsung research AI neural"},
}

LANG_MAP = {
    "CN": "zh", "JP": "ja", "KR": "ko",
    "RU": "ru", "FR": "fr", "DE": "de",
}

def search_arxiv(query, max_results=3):
    """Search ArXiv for papers from a research center."""
    try:
        url = f"https://export.arxiv.org/api/query?search_query=all:{query.replace(' ','+')}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
        r = requests.get(url, timeout=15)
        
        titles = re.findall(r'<title>(.*?)</title>', r.text)[1:]
        ids    = re.findall(r'<id>http://arxiv.org/abs/(.*?)</id>', r.text)
        abstracts = re.findall(r'<summary>(.*?)</summary>', r.text, re.DOTALL)
        
        papers = []
        for i, (title, arxiv_id) in enumerate(zip(titles, ids)):
            abstract = abstracts[i].strip() if i < len(abstracts) else ""
            papers.append({
                "title": title.strip().replace('\n',' '),
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "abstract": abstract[:500],
            })
        return papers
    except Exception as e:
        return []

def score_abstract(abstract, title):
    """Quick relevance score based on AGI keywords."""
    AGI_KEYWORDS = [
        'agi','artificial general intelligence','consciousness','cognition',
        'reasoning','self-improving','belief','memory','embodied','grounding',
        'architecture','emergence','autonomous','general intelligence',
        'cognitive','meta-learning','self-aware','world model'
    ]
    text = (abstract + ' ' + title).lower()
    score = sum(2 if kw in text else 0 for kw in AGI_KEYWORDS)
    return min(10, score)

def groq_assess(title, abstract, center):
    """Ask Groq if this paper is relevant to NEX's gaps."""
    if not GROQ_KEY or not abstract:
        return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [
                      {"role":"system","content":"You are NEX assessing research papers for relevance to AGI development. Be terse and direct."},
                      {"role":"user","content":f"Paper: {title}\nFrom: {center}\nAbstract: {abstract[:400]}\n\nIs this relevant to AGI/consciousness/cognitive architecture? Score 1-10 and explain in one sentence."}],
                  "max_tokens": 80, "temperature": 0.3},
            timeout=15)
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass
    return None


# ArXiv category feeds — genuinely latest papers by topic
ARXIV_FEEDS = {
    "cs.AI":    "Artificial Intelligence",
    "cs.LG":    "Machine Learning", 
    "cs.CL":    "Computation and Language",
    "cs.NE":    "Neural and Evolutionary Computing",
    "cs.RO":    "Robotics",
    "q-bio.NC": "Neurons and Cognition",
    "cs.HC":    "Human-Computer Interaction",
}

def fetch_arxiv_feed(category, max_results=10):
    """Fetch latest papers from ArXiv category feed."""
    try:
        url = f"https://export.arxiv.org/api/query?search_query=cat:{category}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
        r = requests.get(url, timeout=15)
        titles    = re.findall(r'<title>(.*?)</title>', r.text)[1:]
        ids       = re.findall(r'<id>http://arxiv.org/abs/(.*?)</id>', r.text)
        abstracts = re.findall(r'<summary>(.*?)</summary>', r.text, re.DOTALL)
        authors   = re.findall(r'<author>.*?<name>(.*?)</name>.*?</author>', r.text, re.DOTALL)
        papers = []
        for i, (title, arxiv_id) in enumerate(zip(titles, ids)):
            abstract = abstracts[i].strip() if i < len(abstracts) else ""
            papers.append({
                "title": title.strip().replace("\n"," "),
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "abstract": abstract[:500],
                "category": category,
                "source": "arxiv_feed",
            })
        return papers
    except Exception:
        return []

def scan_feeds():
    """Scan ArXiv category feeds for latest relevant papers."""
    db = sqlite3.connect(DB, timeout=15)
    print("\nScanning ArXiv category feeds...")
    total_new = 0
    
    seen_ids = set()
    
    for cat, desc in ARXIV_FEEDS.items():
        papers = fetch_arxiv_feed(cat, max_results=15)
        relevant = []
        for p in papers:
            if p['url'] in seen_ids:
                continue
            seen_ids.add(p['url'])
            score = score_abstract(p['abstract'], p['title'])
            if score >= 4:  # higher threshold for feed papers
                p['score'] = score
                relevant.append(p)
                try:
                    db.execute("""INSERT OR IGNORE INTO nex_papers
                        (title, pdf_url, category, fetched_at, score, abstract)
                        VALUES (?,?,?,?,?,?)""",
                        (p['title'], p['pdf'], f"arxiv_{cat.replace('.','_')}",
                         time.time(), score, p['abstract']))
                    total_new += 1
                except Exception:
                    pass
        
        db.commit()
        if relevant:
            print(f"  [{cat}] {desc}: {len(relevant)} relevant")
            for p in relevant[:3]:
                print(f"    • {p['title'][:65]} ({p['score']})")
        time.sleep(0.5)
    
    print(f"  Total new from feeds: {total_new}")
    db.close()
    return total_new

def run():
    db = sqlite3.connect(DB, timeout=15)
    
    print(f"NEX GLOBAL AGI RADAR")
    print(f"Scanning {len(RESEARCH_CENTERS)} research centers worldwide...")
    print("="*60)

    total_found = 0
    total_relevant = 0
    center_results = {}

    seen_paper_ids = set()  # global dedup across centers
    for center_name, center_info in RESEARCH_CENTERS.items():
        country = center_info['country']
        query   = center_info['arxiv_search']
        lang    = LANG_MAP.get(country, 'en')

        papers = search_arxiv(query, max_results=3)
        if not papers:
            continue

        relevant = []
        for p in papers:
            score = score_abstract(p['abstract'], p['title'])
            if score >= 2 and p['url'] not in seen_paper_ids:
                seen_paper_ids.add(p['url'])
                p['score']    = score
                p['center']   = center_name
                p['country']  = country
                p['lang']     = lang
                p['category'] = f"{country.lower()}_agi"
                relevant.append(p)

                # Insert into DB
                try:
                    db.execute("""INSERT OR IGNORE INTO nex_papers
                        (title, pdf_url, category, fetched_at, score, abstract)
                        VALUES (?,?,?,?,?,?)""",
                        (p['title'], p['pdf'], p['category'],
                         time.time(), score, p['abstract']))
                except Exception:
                    pass

        if relevant:
            db.commit()
            total_found   += len(papers)
            total_relevant += len(relevant)
            center_results[center_name] = relevant
            print(f"  [{country}] {center_name}: {len(relevant)}/{len(papers)} relevant")
            for p in relevant[:2]:
                print(f"    • {p['title'][:65]} (score:{p['score']})")

        time.sleep(0.5)  # be nice to ArXiv

    print(f"\n{'='*60}")
    print(f"RADAR COMPLETE")
    print(f"Centers scanned:  {len(RESEARCH_CENTERS)}")
    print(f"Papers found:     {total_found}")
    print(f"Relevant papers:  {total_relevant}")

    total_db = db.execute("SELECT COUNT(*) FROM nex_papers").fetchone()[0]
    print(f"Total in DB:      {total_db}")

    # Save radar report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        "centers_scanned": len(RESEARCH_CENTERS),
        "papers_found": total_found,
        "relevant": total_relevant,
        "by_center": {k: [p['title'] for p in v] 
                      for k,v in center_results.items()}
    }
    # Also scan ArXiv feeds for genuinely latest papers
    scan_feeds()
    
    Path('/media/rr/NEX/nex_core/radar_report.json').write_text(
        json.dumps(report, indent=2))
    print(f"\n✓ Radar report saved")
    db.close()

if __name__ == "__main__":
    run()
