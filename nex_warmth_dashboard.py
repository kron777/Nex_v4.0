"""
nex_warmth_dashboard.py
Item 9 — Warmth Visualiser Dashboard.

Real-time terminal dashboard showing NEX's cognitive warmth state.
Refreshes every 30 seconds. Shows the invisible made visible.

Panels:
  1. WARMTH DISTRIBUTION — bar chart of warmth levels
  2. TOP WARM WORDS      — hottest words with full tag display
  3. FASTEST WARMING     — velocity leaders
  4. PRIORITY QUEUE      — what's warming next
  5. TENSION GRAPH       — active conceptual tensions
  6. VALENCE MAP         — emotional register overview
  7. BELIEF GENERATION   — warmth-generated beliefs count
  8. DAILY METRICS       — beliefs/words/phrases added today
  9. CRON STATUS         — when each job last ran
"""
import sqlite3, time, os, sys, json
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / "Desktop/nex/nex.db"
NEX_DIR = Path.home() / "Desktop/nex"

DEPTH_NAMES = {
    1:"shallow", 2:"semi_mid", 3:"mid",
    4:"semi_deep", 5:"deep", 6:"soul"
}

def _get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db

def _clear():
    os.system("clear")

def _bar(value, max_val, width=30, char="█") -> str:
    if max_val == 0:
        return " " * width
    filled = int(width * value / max_val)
    return char * filled + "░" * (width - filled)

def _pct(n, total) -> str:
    if total == 0: return "0.0%"
    return f"{n/total*100:.1f}%"

def _safe(db, sql, params=(), default=0):
    try:
        r = db.execute(sql, params).fetchone()
        return r[0] if r else default
    except Exception:
        return default

def render_dashboard():
    db = _get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    W = 72  # terminal width

    _clear()

    # ── HEADER ────────────────────────────────────────────────
    print("╔" + "═"*(W-2) + "╗")
    print(f"║{'NEX COGNITIVE WARMTH DASHBOARD':^{W-2}}║")
    print(f"║{now:^{W-2}}║")
    print("╠" + "═"*(W-2) + "╣")

    # ── WARMTH DISTRIBUTION ───────────────────────────────────
    total_w = _safe(db, "SELECT COUNT(*) FROM word_tags")
    core_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.8")
    hot_w   = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.6 AND w<0.8")
    warm_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.4 AND w<0.6")
    tepid_w = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w>=0.2 AND w<0.4")
    cold_w  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE w<0.2")
    nosrch  = _safe(db, "SELECT COUNT(*) FROM word_tags WHERE f=0")

    print(f"║{'  WORD WARMTH DISTRIBUTION':<{W-2}}║")
    print(f"║{'  Total: '+str(total_w)+' words  |  Search-skippable: '+str(nosrch)+' ('+_pct(nosrch,total_w)+')':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    max_bucket = max(core_w, hot_w, warm_w, tepid_w, cold_w, 1)
    for label, count, symbol in [
        ("CORE  ≥0.80", core_w,  "🔥"),
        ("HOT   ≥0.60", hot_w,   "♨ "),
        ("WARM  ≥0.40", warm_w,  "○ "),
        ("TEPID ≥0.20", tepid_w, "· "),
        ("COLD  <0.20", cold_w,  "  "),
    ]:
        bar = _bar(count, max_bucket, width=25)
        print(f"║  {symbol} {label:12} {bar} {count:5} {_pct(count,total_w):>6}  ║")

    # ── TOP WARM WORDS ────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TOP WARM WORDS':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    top_words = db.execute("""SELECT word, w, d, a, e, c, f,
        b, s, g FROM word_tags
        ORDER BY w DESC LIMIT 12""").fetchall()

    print(f"║  {'WORD':18} {'W':5} {'D':9} {'ALIGN':6} "
          f"{'VAL':5} {'B':4} {'SRCH':4} ║")
    print(f"║  {'─'*18} {'─'*5} {'─'*9} {'─'*6} "
          f"{'─'*5} {'─'*4} {'─'*4} ║")

    for r in top_words:
        search = "·" if r["f"] == 0 else "⚡"
        depth  = DEPTH_NAMES.get(r["d"], "?")[:9]
        align  = f"{r['a']:+.2f}" if r["a"] else " 0.00"
        val    = f"{r['e']:+.2f}" if r["e"] else " 0.00"
        print(f"║  {r['word']:18} "
              f"{r['w']:.3f} "
              f"{depth:9} "
              f"{align:6} "
              f"{val:5} "
              f"{r['b'] or 0:4} "
              f"{search:>4}  ║")

    # ── FASTEST WARMING ───────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  FASTEST WARMING (velocity leaders)':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    vel_words = db.execute("""SELECT word, w, vel, delta
        FROM word_tags WHERE vel > 0
        ORDER BY vel DESC LIMIT 6""").fetchall()

    if vel_words:
        for r in vel_words:
            bar = _bar(r["vel"] or 0, 1.0, width=20)
            print(f"║  {r['word']:20} "
                  f"w={r['w']:.3f} "
                  f"vel={r['vel']:.3f} "
                  f"{bar}  ║")
    else:
        print(f"║  {'No velocity data yet':^{W-4}}  ║")

    # ── PRIORITY QUEUE ────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  WARMING QUEUE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    try:
        queue_stats = db.execute("""SELECT priority,
            COUNT(*) as n, MAX(gap_count) as max_gaps
            FROM warming_queue GROUP BY priority
            ORDER BY CASE priority
                WHEN 'urgent' THEN 1 WHEN 'high' THEN 2
                WHEN 'normal' THEN 3 WHEN 'low' THEN 4
            END""").fetchall()

        total_q = sum(r["n"] for r in queue_stats)
        for r in queue_stats:
            bar = _bar(r["n"], total_q, width=20)
            print(f"║  {r['priority']:8} {bar} "
                  f"{r['n']:5}  max_gaps={r['max_gaps'] or 0}  ║")
        print(f"║  {'TOTAL':8} {'':20} {total_q:5}"
              f"{'':14}║")

        # Show top urgent words
        urgent = db.execute("""SELECT word, gap_count
            FROM warming_queue WHERE priority='urgent'
            ORDER BY gap_count DESC LIMIT 4""").fetchall()
        if urgent:
            words_str = "  urgent: " + ", ".join(
                f"{r['word']}({r['gap_count']})"
                for r in urgent)
            print(f"║{words_str:<{W-2}}║")
    except Exception:
        print(f"║  {'Queue unavailable':^{W-4}}  ║")

    # ── TENSIONS & VALENCE ────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TENSIONS & VALENCE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    t_edges = _safe(db, "SELECT COUNT(*) FROM tension_graph")
    t_words = _safe(db,
        "SELECT COUNT(DISTINCT word_a) FROM tension_graph")

    try:
        v_edges = _safe(db,
            "SELECT COUNT(*) FROM valence_chains")
        v_neg   = _safe(db,
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='negative'")
        v_pos   = _safe(db,
            "SELECT COUNT(*) FROM valence_chains "
            "WHERE chain_type='positive'")
        print(f"║  Tension graph : {t_edges:4} edges  "
              f"across {t_words} words{'':<14}║")
        print(f"║  Valence chains: {v_edges:4} edges  "
              f"neg={v_neg} pos={v_pos}{'':18}║")
    except Exception:
        print(f"║  Tension graph : {t_edges:4} edges  "
              f"across {t_words} words{'':14}║")
        print(f"║  Valence chains: not yet built"
              f"{'':30}║")

    # Show top tensions
    top_t = db.execute("""SELECT word_a, word_b,
        friction_type, strength
        FROM tension_graph WHERE word_a < word_b
        ORDER BY strength DESC LIMIT 4""").fetchall()
    for r in top_t:
        print(f"║    {r['word_a']:14}←→{r['word_b']:14}"
              f"[{r['friction_type'][:10]:10}] "
              f"s={r['strength']:.2f}{'':3}║")

    # ── BELIEFS ───────────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  BELIEF GRAPH':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    total_b  = _safe(db, "SELECT COUNT(*) FROM beliefs")
    high_b   = _safe(db,
        "SELECT COUNT(*) FROM beliefs WHERE confidence>=0.75")
    warmth_b = _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%warmth%'")
    tension_b= _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%tension%'")
    cluster_b= _safe(db,
        "SELECT COUNT(*) FROM beliefs "
        "WHERE source LIKE '%cluster%'")

    print(f"║  Total beliefs       : {total_b:,}{'':26}║")
    print(f"║  High confidence     : {high_b:,} "
          f"({_pct(high_b,total_b)}){'':16}║")
    print(f"║  Warmth-generated    : {warmth_b:,} "
          f"(tension={tension_b} cluster={cluster_b}){'':6}║")

    # ── TRAINING DATA ─────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║{'  TRAINING PIPELINE':<{W-2}}║")
    print("║" + "─"*(W-2) + "║")

    td = NEX_DIR / "training_data"
    total_pairs = 0
    warmth_pairs= 0
    if td.exists():
        for f in td.glob("*.jsonl"):
            try:
                n = sum(1 for _ in open(f))
                total_pairs += n
                if "warmth" in f.name:
                    warmth_pairs += n
            except Exception:
                pass

    print(f"║  Total training pairs: {total_pairs:,}{'':25}║")
    print(f"║  Warmth pairs        : {warmth_pairs:,}{'':25}║")

    # ── PHRASES ───────────────────────────────────────────────
    total_p = _safe(db, "SELECT COUNT(*) FROM phrase_tags")
    warm_p  = _safe(db,
        "SELECT COUNT(*) FROM phrase_tags WHERE w>=0.35")
    print(f"║  Phrase tags         : {total_p:,} "
          f"({warm_p} warm){'':19}║")

    # ── FOOTER ────────────────────────────────────────────────
    print("╠" + "═"*(W-2) + "╣")
    print(f"║  {'Refreshes every 30s  |  Ctrl+C to exit':^{W-4}}  ║")
    print("╚" + "═"*(W-2) + "╝")

    db.close()


def run_dashboard(refresh=30, once=False):
    """Run the dashboard, refreshing every N seconds."""
    if once:
        render_dashboard()
        return

    print("Starting NEX Warmth Dashboard "
          "(Ctrl+C to stop)...")
    time.sleep(1)

    try:
        while True:
            render_dashboard()
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
        help="Render once and exit")
    parser.add_argument("--refresh", type=int, default=30,
        help="Refresh interval in seconds")
    args = parser.parse_args()
    run_dashboard(refresh=args.refresh, once=args.once)
