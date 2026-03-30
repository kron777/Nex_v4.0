"""Safe tick shim — wraps functions or objects that may lack .tick()"""

def safe_tick(obj, label=""):
    try:
        if hasattr(obj, "tick"):
            obj.tick()
        elif callable(obj):
            obj()
    except Exception as e:
        pass  # suppress tick errors silently

def safe_get_signals(obj, n=3):
    try:
        if hasattr(obj, "get_top_signals"):
            return obj.get_top_signals(n)
        return []
    except Exception:
        return []
