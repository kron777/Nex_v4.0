"""
nex_warmth_dashboard_cyber.py
Cyberpunk terminal dashboard — opens in browser.
Run: venv/bin/python3 nex_warmth_dashboard_cyber.py
"""
import sqlite3, json, time, webbrowser, http.server
import threading
from pathlib import Path

DB = Path.home() / "Desktop/nex/nex.db"

def get_data():
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row
    d = {}
    def q(sql, p=(), default=0):
        try: return db.execute(sql,p).fetchone()[0] or default
        except: return default
    d["beliefs"]   = q("SELECT COUNT(*) FROM beliefs")
    d["high_b"]    = q("SELECT COUNT(*) FROM beliefs WHERE confidence>=0.75")
    d["warmth_b"]  = q("SELECT COUNT(*) FROM beliefs WHERE source LIKE '%warmth%'")
    d["total_w"]   = q("SELECT COUNT(*) FROM word_tags")
    d["hot_w"]     = q("SELECT COUNT(*) FROM word_tags WHERE w>=0.6")
    d["warm_w"]    = q("SELECT COUNT(*) FROM word_tags WHERE w>=0.4 AND w<0.6")
    d["tepid_w"]   = q("SELECT COUNT(*) FROM word_tags WHERE w>=0.2 AND w<0.4")
    d["cold_w"]    = q("SELECT COUNT(*) FROM word_tags WHERE w<0.2")
    d["nosrch"]    = q("SELECT COUNT(*) FROM word_tags WHERE f=0")
    d["phrases"]   = q("SELECT COUNT(*) FROM phrase_tags")
    d["tensions"]  = q("SELECT COUNT(*) FROM tension_graph")
    d["queue"]     = q("SELECT COUNT(*) FROM warming_queue")
    d["urgent"]    = q("SELECT COUNT(*) FROM warming_queue WHERE priority='urgent'")
    d["high_q"]    = q("SELECT COUNT(*) FROM warming_queue WHERE priority='high'")
    try:
        top = db.execute("SELECT word,w,d FROM word_tags ORDER BY w DESC LIMIT 12").fetchall()
        d["top_words"] = [{"w":r["word"],"v":r["w"],"d":r["d"]} for r in top]
    except: d["top_words"] = []
    db.close()
    return d

if __name__ == "__main__":
    data = get_data()
    print(f"NEX Warmth: {data['hot_w']} hot words, {data['beliefs']:,} beliefs")
    print("Dashboard data loaded. Integrate with your web server.")
