import sys
# from urllib.parse import urlparse
from datetime import datetime
from sanic import Sanic  # pip install sanic
from sanic import response
from sanic_jinja2 import SanicJinja2  # pip install sanic-jinja2
from x115 import Connect115

app = Sanic()
jinja = SanicJinja2(app)
x115 = Connect115()
port = 8001


@app.route(r"/<full_path:[\w/\W]*>", methods=('GET', 'HEAD'), host=f"my.115.com:{port}")
@jinja.template('ls.html')
async def ls(request, full_path):
    full_path = '/' + full_path.strip()
    if full_path == 'favicon.ico':
        return response.raw(b'')
    print(request.headers, full_path)
    ls = x115.path[full_path]
    if not ls or len(ls) <= 2:
        ls = x115.listdir(full_path)
    if request.method == "HEAD":
        code = 200
        if not ls:
            code = 404
            size = 0
        else:
            size = ls.get('size', 0)
            mod_time = datetime.utcfromtimestamp(ls['time']).strftime('%a, %d %b %Y %H:%M:%S GMT')
        return response.raw(b'', headers={'Content-Length': size, 'Last-Modified': mod_time}, status=code)
    if 'pickcode' in ls:
        r = x115._get_link(ls['pickcode'])
        url = r.json()['file_url']
        cookie = r.headers.get('Set-Cookie')
        # if cookie:
        #     cookie = cookie.replace('domain=115.com', 'domain=' + urlparse(url).netloc)
        #     cookie = cookie.split(';', 1)[0] + '; domain=' + urlparse(url).netloc
        return response.redirect(url.replace('http://', 'https://'), headers={'Set-Cookie': cookie})
    else:
        return {'root': full_path, 'ls': ls}


if __name__ == "__main__":
    host = '127.0.0.1'
    port = 8001
    try:
        host = sys.argv[1]
        port = sys.argv[2]
    except:
        pass
    app.run(host=host, port=port)
