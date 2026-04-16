#!/usr/bin/env python3
"""
nex_reading_list_feeder.py — Feed books from reading_list.txt into NEX
Usage: python3 nex_reading_list_feeder.py [--mode pivotal|core|enjoy] [--limit N]
"""
import subprocess, sys, time, json
from pathlib import Path

FEEDER = "/media/rr/NEX/nex_core/nex_book_feeder.py"
LIST   = Path(__file__).parent / "reading_list.txt"
DONE   = Path(__file__).parent / "reading_list_done.json"
VENV   = Path(__file__).parent / "venv/bin/python3"
PYTHON = str(VENV) if VENV.exists() else sys.executable

def load_done():
    if DONE.exists():
        return set(json.loads(DONE.read_text()))
    return set()

def save_done(done):
    DONE.write_text(json.dumps(list(done), indent=2))

def parse_list():
    books = []
    for line in LIST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        books.append(line)
    return books

def feed_book(title, mode):
    print(f"\n{'='*60}")
    print(f"FEEDING: {title} [{mode}]")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            [PYTHON, FEEDER, "--search", title, "--mode", mode],
            timeout=600,
            input=b"1\n",  # auto-select first result
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {title}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode",  default="pivotal", choices=["pivotal","core","enjoy"])
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--list",  action="store_true", help="Just list books")
    args = p.parse_args()

    books = parse_list()
    done  = load_done()

    print(f"NEX READING LIST FEEDER")
    print(f"Books in list:  {len(books)}")
    print(f"Already done:   {len(done)}")
    print(f"Mode:           {args.mode}")
    print()

    if args.list:
        for i, b in enumerate(books):
            status = "✓" if b in done else "·"
            print(f"  {status} [{i:2d}] {b}")
        sys.exit(0)

    fed = 0
    for i, book in enumerate(books):
        if i < args.start:
            continue
        if book in done:
            print(f"  SKIP (done): {book}")
            continue
        if args.limit and fed >= args.limit:
            print(f"\nLimit of {args.limit} reached — stopping")
            break

        success = feed_book(book, args.mode)
        if success:
            done.add(book)
            save_done(done)
            fed += 1
            print(f"  ✓ completed: {book}")
        else:
            print(f"  ✗ failed: {book}")
        time.sleep(3)

    print(f"\n{'='*60}")
    print(f"✓ Fed {fed} books | {len(done)}/{len(books)} total done")
