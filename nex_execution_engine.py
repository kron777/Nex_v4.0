"""
nex_execution_engine.py — Execution engine for NEX
Queues and executes deferred actions: research tasks, belief updates,
throw_net sessions triggered by other modules.
"""
import os, sys, sqlite3, json, logging, threading, time
from collections import deque
_ROOT = os.path.expanduser("~/Desktop/nex")
for _p in [_ROOT, os.path.join(_ROOT,"nex")]:
    if _p not in sys.path: sys.path.insert(0, _p)
log = logging.getLogger("nex_execution_engine")
_DB = os.path.join(_ROOT, "nex.db")
_instance = None

class ExecutionEngine:
    def __init__(self):
        self._queue   = deque(maxlen=100)
        self._ready   = False
        self._lock    = threading.Lock()
        self._worker  = None

    def init(self):
        try:
            con = sqlite3.connect(_DB)
            con.execute("""CREATE TABLE IF NOT EXISTS execution_queue (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type  TEXT NOT NULL,
                payload    TEXT,
                status     TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                run_at     TEXT DEFAULT (datetime('now')))""")
            con.commit()
            # Load pending tasks
            rows = con.execute("""
                SELECT id, task_type, payload FROM execution_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC LIMIT 20
            """).fetchall()
            con.close()
            with self._lock:
                for row in rows:
                    self._queue.append({
                        "id": row[0], "type": row[1],
                        "payload": json.loads(row[2] or "{}")
                    })
            self._ready = True
            self._worker = threading.Thread(
                target=self._run_loop, daemon=True, name="nex_execution")
            self._worker.start()
            log.info(f"ExecutionEngine init: {len(rows)} pending tasks loaded")
        except Exception as e:
            log.warning(f"ExecutionEngine.init: {e}")
            self._ready = True

    def enqueue(self, task_type: str, payload: dict = None):
        with self._lock:
            self._queue.append({"type": task_type, "payload": payload or {}})
        try:
            con = sqlite3.connect(_DB)
            con.execute("""INSERT INTO execution_queue (task_type, payload)
                VALUES (?, ?)""", (task_type, json.dumps(payload or {})))
            con.commit(); con.close()
        except Exception as e:
            log.warning(f"enqueue DB write: {e}")

    def _run_loop(self):
        while True:
            task = None
            with self._lock:
                if self._queue:
                    task = self._queue.popleft()
            if task:
                self._execute(task)
            time.sleep(5)

    def _execute(self, task: dict):
        ttype = task.get("type","")
        payload = task.get("payload", {})
        try:
            if ttype == "throw_net":
                from nex.nex_throw_net import ThrowNetEngine
                constraint = payload.get("constraint", "general improvement")
                ThrowNetEngine(_DB).run(constraint, trigger_mode="autonomous")
            elif ttype == "research":
                query = payload.get("query", "")
                if query:
                    log.info(f"[EE] research: {query[:60]}")
            else:
                log.info(f"[EE] task: {ttype}")
            # Mark done
            task_id = task.get("id")
            if task_id:
                con = sqlite3.connect(_DB)
                con.execute("""UPDATE execution_queue SET status='done'
                    WHERE id=?""", (task_id,))
                con.commit(); con.close()
        except Exception as e:
            log.warning(f"_execute {ttype}: {e}")

    def queue_size(self) -> int:
        with self._lock: return len(self._queue)

def get_execution_engine() -> ExecutionEngine:
    global _instance
    if _instance is None:
        _instance = ExecutionEngine()
    return _instance
