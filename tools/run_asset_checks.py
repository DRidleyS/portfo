import requests
paths=['/','/static/assets/css/main.css','/static/assets/js/main.js','/static/assets/js/browser.min.js','/static/assets/js/util.js','/static/images/overlay.png','/static/images/dslogo.png']
for p in paths:
    try:
        r=requests.get('http://127.0.0.1:5000'+p,timeout=5)
        print(p, r.status_code)
    except Exception as e:
        print(p, 'ERR', e)
