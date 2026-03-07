from .agent_tools import dispatch

def route_command(text):

    parts = text.strip().split(" ",1)
    cmd = parts[0]

    args = ""
    if len(parts) > 1:
        args = parts[1]

    try:
        result = dispatch(cmd, args)
        return True, result
    except Exception:
        return False, None
