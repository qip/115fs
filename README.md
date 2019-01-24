# 1. Install
  with python >= 3.6,
  `pip install -r requirements.txt`

# 2. Configure
## 2.1 Cookie
edit `cookie.json` accordingly.
## 2.2 Update hosts (For http index server only)
update hosts file to point `my.115.com` to server.py service.

# 3. Usage
## 3.1 As filesystem
`python3.6 fs.py /media/115`
## 3.2 As http index server
`python3.6 server.py 0.0.0.0 8000`
