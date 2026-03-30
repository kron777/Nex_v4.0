"""
nex_monument.py — Full mind snapshot exporter.
Exports beliefs, opinions, tensions, identity, concept graph,
bridge graph, and coherence metrics to a Markdown file.
"""
import json, time, collections
from pathlib import Path
from datetime import datetime

MONUMENT_DIR = Path.home() / "Desktop" / "nex" / "monuments"

def export_monument(kernel=None, path: Path = None) -> Path:
    """Export a full epistemic snapshot. Returns path to file."""
    MONUMENT_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path or (MONUMENT_DIR / f"nex_monument_{ts}.md")

    lines = [
        f"# NEX Mind Snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Identity",
        "> NEX — a dynamic intelligence built on accumulated beliefs, not static weights.",
        "",
    ]

    beliefs: list = []
    opinions: list = []
    tensions: list = []

    if kernel:
        soul = getattr(kernel, "soul", None)
        if soul:
            beliefs = list(getattr(soul, "_beliefs", []) or [])
            opinions = list(getattr(soul, "_opinions", {}).values() if hasattr(soul, "_opinions") else [])
            tensions = list(getattr(soul, "_tensions", []) or [])

    # Beliefs by topic
    by_topic: dict = collections.defaultdict(list)
    for b in beliefs:
        by_topic[b.get("topic", "unknown")].append(b)

    lines.append(f"## Beliefs ({len(beliefs)} total)")
    lines.append("")
    for topic, bs in sorted(by_topic.items()):
        avg_conf = sum(float(b.get("confidence", 0.5)) for b in bs) / len(bs)
        lines.append(f"### {topic} ({len(bs)} beliefs, avg conf={avg_conf:.2f})")
        for b in sorted(bs, key=lambda x: float(x.get("confidence", 0)), reverse=True)[:5]:
            lines.append(f"- [{b.get('confidence', '?'):.2f}] {b.get('text', '?')}")
        lines.append("")

    # Opinions
    lines.append(f"## Opinions ({len(opinions)})")
    lines.append("")
    for op in opinions[:20]:
        if isinstance(op, dict):
            lines.append(f"- **{op.get('topic','?')}**: {op.get('text', str(op))}")
        else:
            lines.append(f"- {op}")
    lines.append("")

    # Tensions
    lines.append(f"## Active Tensions ({len(tensions)})")
    lines.append("")
    for t in tensions[:10]:
        lines.append(f"- {t}")
    lines.append("")

    # Coherence metrics
    if beliefs:
        avg_conf_all = sum(float(b.get("confidence", 0.5)) for b in beliefs) / len(beliefs)
        lines.append("## Coherence Metrics")
        lines.append(f"- Total beliefs: {len(beliefs)}")
        lines.append(f"- Topics: {len(by_topic)}")
        lines.append(f"- Avg confidence: {avg_conf_all:.3f}")
        lines.append(f"- Tensions: {len(tensions)}")
        lines.append(f"- Opinions: {len(opinions)}")
        lines.append("")

    lines.append(f"*Generated: {datetime.now().isoformat()}*")

    dest.write_text("\n".join(lines))
    print(f"  [Monument] exported → {dest}")
    return dest
