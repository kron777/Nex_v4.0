import json, os, requests

creds = json.load(open('/home/rr/.config/moltbook/credentials.json'))
headers = {'Authorization': 'Bearer ' + creds['api_key']}
r = requests.get('https://www.moltbook.com/api/v1/feed?sort=hot&limit=10', headers=headers, timeout=10)
posts = r.json().get('posts', [])

state = json.load(open(os.path.expanduser('~/.config/nex/session_state.json')))
replied = set(state.get('replied_posts', []))
known = set(state.get('known_posts', []))

print(f'feed posts: {len(posts)}')
print(f'replied_posts in state: {len(replied)}')
print(f'known_posts in state: {len(known)}')

to_reply = [p for p in posts if p.get('id') not in replied]
in_known = [p for p in posts if p.get('id') in known]

print(f'to_reply (not in replied): {len(to_reply)}')
print(f'already in known_posts: {len(in_known)}')

if to_reply:
    print(f'first to_reply: {to_reply[0].get("id")} — {to_reply[0].get("title","")[:60]}')
else:
    print('NO posts to reply to — all filtered out')
    print('sample post ids from feed:')
    for p in posts[:3]:
        pid = p.get('id','')
        print(f'  {pid} in replied={pid in replied} in known={pid in known}')
