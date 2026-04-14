lines = open('/home/rr/Desktop/nex/nex_telegram.py').readlines()
out = []
i = 0
while i < len(lines):
    line = lines[i]
    # Find the "except Exception as e:" inside _resilient_polling (line 24, index 23)
    if i == 23 and 'except Exception as e:' in line:
        out.append(line)  # keep except line
        out.append('                err_str = str(e)\n')
        out.append('                if "Conflict" in err_str:\n')
        out.append('                    print(f"  [Telegram] conflict — retrying in 10s...")\n')
        out.append('                    await _asyncio.sleep(10)\n')
        out.append('                else:\n')
        i += 1  # skip original print line
        out.append('                    ' + lines[i].lstrip())  # print fatal error (indented)
        i += 1  # skip raise
        out.append('                    ' + lines[i].lstrip())  # raise (indented)
    else:
        out.append(line)
    i += 1
open('/home/rr/Desktop/nex/nex_telegram.py', 'w').writelines(out)
print('done')
