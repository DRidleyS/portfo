import requests
paths=['/','/static/assets/css/main.css','/static/images/dslogo.png','/static/assets/css/noscript.css']
for p in paths:
    try:
        r=requests.get('http://127.0.0.1:5000'+p,timeout=5)
        print(p, r.status_code, 'len=', len(r.content))
    except Exception as e:
        print(p, 'ERR', e)
