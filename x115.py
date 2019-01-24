import json
import time
import functools
import collections
import requests
import sys
if sys.platform == 'win32':
    import posixpath as ppath
else:
    import os.path as ppath

referer = {'webapi': 'https://webapi.115.com/bridge_2.0.html?namespace=Core.DataAccess&api=UDataAPI&_t=v5',
           'aps': 'https://aps.115.com/bridge_2.0.html?namespace=Core.DataAccess&api=DataAPSAPI&_t=v5',
           '115': 'https://115.com/?cid={}&offset=0&tab=download&mode=wangpan'
           }

headers = {
           'Accept-Encoding': 'gzip, deflate, br',
           'Accept-Language': 'en-US,en;q=0.8,zh-CN;q=0.6,zh;q=0.4,zh-TW;q=0.2',
           'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.80 Safari/537.36',
           'Accept': '*/*',
           'Referer': referer['webapi'],
           'X-Requested-With': 'XMLHttpRequest'
           }

cookies = json.loads(open('cookie.json').read())

origin = {'webapi': 'https://webapi.115.com',
          '115': 'https://115.com'
          }

content_type = {'api': 'application/x-www-form-urlencoded',
                'web': 'application/x-www-form-urlencoded; charset=UTF-8'
                }


class Connect115(object):
    def __init__(self):
        """
        self.dirs: a copy of directory structure with directory id as key and name as value
        self._dirs_lookup: a copy of directories' parent paths
        self.path:
            {
                "/": {
                    "dir1": {
                        "file1.ext": { "time": 12345, "size": 1048576, "pc": "abcde" },
                        "file2.ext": { "time": 12346, "size": 1048576, "pc": "fghij" },
                        "time": 11111
                    },
                    "dir2": {
                        "dir3": {"time": 22222},
                        "time": 123123
                    },
                    "time": 0
                }
            }
        """
        self.cache_time = 10 * 60
        self.s = requests.Session()
        self.s.headers.update(headers)
        for i in cookies:
            self.s.cookies.set(**i)
        self.default_dir = 0
        self.uid = self.s.cookies.get('UID').split('_', 1)[0]
        self.sign = ''
        self.time = 0
        self._fs = {'last_update': 0}
        self.dirs = {0: {}}
        self._dirs_lookup = {}
        self.path = self.Path()
        self.path['/'] = {"time": 0, "cid": 0}
        self.listdir('/')

    # noinspection PyCallByClass
    class Path(collections.MutableMapping, dict):
        # doesn't allow same name for file and directory
        def __getitem__(self, key):
            # assume always abspath
            _path = key.strip('/')
            if _path:
                path = ['/'] + _path.split('/')
            else:
                path = ['/']
            try:
                result = {}
                node = functools.reduce(dict.__getitem__, path, self)
                if 'cid' in node:  # is dir
                    for k, v in node.items():
                        result[k] = v
                else:  # is file
                    for k in ['time', 'size', 'fid', 'pickcode', 'sha']:
                        result[k] = node[k]
                return result
            except KeyError:
                # TODO: retrieve path from remote first
                return False

        def __setitem__(self, key, value):
            dict.__setitem__(self, key, value)

        def setpath(self, parent, key, value):
            _path = parent.strip('/')
            key = key.strip('/')
            if _path:
                path = ['/'] + _path.split('/')
            else:
                path = ['/']
            d = functools.reduce(dict.__getitem__, path, self)
            if key in d:
                d[key].update(value)
            else:
                d[key] = value

        def __delitem__(self, key):
            dict.__delitem__(self, key)

        def __iter__(self):
            return dict.__iter__(self)

        def __len__(self):
            return dict.__len__(self)

        def __contains__(self, key):
            return dict.__contains__(self, key)

    def update_sign(self):
        url = 'https://115.com/?ct=offline&ac=space&_={}'.format(int(time.time() * 1e3))
        result = self.s.get(url, headers={'Referer': referer['115'].format(self.default_dir)}).json()
        self.sign = result['sign']
        self.time = result['time']

    def fs(self) -> dict:
        now = time.time()
        if self._fs['last_update'] + self.cache_time < now:
            url = 'https://webapi.115.com/files/index_info'
            result = self.s.get(url, headers={'Referer': referer['115'].format(self.default_dir)}).json()
            self._fs = {'last_update': now, 'free': result['data']['space_info']['all_remain']['size'], 'total': result['data']['space_info']['all_total']['size']}
        return self._fs

    def listdir(self, path):
        # TODO: proper caching
        if not path.startswith('/'):
            path = '/' + path
        path = ppath.abspath(path)
        result = self.path[path]
        if result and 'cid' in result and len(result) > 2:
            del result['cid']
            # del result['time']
            return result
        if path == '/':
            return self._listdir(path)
        parent = path.strip('/').rsplit('/', 1)[0]
        self._listdir(parent)
        self._listdir(path)
        self.listdir(parent)
        result = self.path[path]
        if 'cid' in result:  # is dir
            del result['cid']
            # del result['time']
        return result

    def _listdir(self, path):
        print('listdir', path)
        if not self.path[path] or 'cid' not in self.path[path] or len(self.path[path]) > 2:
            return
        for i in self.ls(self.path[path]['cid']):
            if 'te' in i:
                i['t'] = i['te']
            if 's' in i:
                self.path.setpath(path, i['n'], {'time': int(i['t']), 'size': int(i['s']), 'fid': int(i['fid']), 'pickcode': i['pc'], 'sha': i['sha']})
            else:
                self.path.setpath(path, i['n'], {'time': int(i['t']), 'cid': int(i['cid'])})

    def ls(self, folder_id: int = -1) -> list:
        """
        list files and directories under directory
        :param folder_id: folder id as int
        :return: dict: [{
            "fid": "1162242889158390665",
            "uid": 362421191,
            "aid": 1,
            "cid": "549407930018067068",
            "n": "cn_office_professional_plus_2016_x86_x64_dvd_6969182.iso",
            "s": 2588266496,
            "sta": 1,
            "pt": "0",
            "pc": "bxqykdkhrffqs8son",
            "p": 0,
            "m": 0,
            "t": "2017-10-21 14:09",
            "te": "1508566149",
            "tp": "1508566149",
            "d": 1,
            "c": 0,
            "sh": 0,
            "e": "",
            "ico": "iso",
            "fatr": "",
            "sha": "277926A41B472EE38CA0B36ED8F2696356DCC98F",
            "q": 0,
            "hdf": 0,
            "et": 0,
            "epos": "",
            "fl": []
        }]
        """
        print('ls', folder_id)
        if folder_id == -1:
            folder_id = self.default_dir
        url = 'https://webapi.115.com/files?aid=1&cid={}&o=user_ptime&asc=0&offset=0&show_dir=1&limit=115&code=&scid=' \
              '&snap=0&natsort=1&custom_order=2&source=&format=json&type=&star=&is_q=&is_share='.format(folder_id)
        result = self.s.get(url, headers={'Referer': referer['115'].format(self.default_dir)}).json()
        if result['errNo'] == 0:
            data = result['data']
            return data

    def dir(self, folder_id: int = 0) -> list:
        """
        list directory content
        :param folder_id: folder id as int
        :return: list of dict: [{
            "cid": "575374660116574228",
            "aid": "1",
            "pid": "0",
            "n": "\u624b\u673a\u76f8\u518c",
            "m": 0,
            "cc": "",
            "sh": "0",
            "pc": "fbljjj7zqyt4tmwson",
            "t": "1438606004",
            "e": "",
            "p": 0,
            "ns": "\u624b\u673a\u76f8\u518c",
            "u": "",
            "fc": 0,
            "hdf": 0
        }
        """
        url = 'https://aps.115.com/natsort/files.php?aid=1&cid={}&offset=0&limit=50&show_dir=1&o=file_name&asc=1&nf=1' \
              '&qid=0&natsort=1&source=&format=json'.format(folder_id)
        result = self.s.get(url, headers={'Referer': referer['aps']}).json()
        if result['errNo'] == 0:
            data = result['data']
            for folder in data:
                name = folder['n']
                parent_id = int(folder['pid'])
                folder_id = int(folder['cid'])
                if parent_id == 0:
                    self._dirs_lookup[folder_id] = [0]
                else:
                    self._dirs_lookup[folder_id] = self._dirs_lookup[parent_id] + [parent_id]  # TODO: pid not in lookup
                if not self.default_dir and name == '云下载':
                    self.default_dir = folder_id
                parents = self._dirs_lookup[folder_id]
                parent = functools.reduce(dict.__getitem__, parents, self.dirs)
                if folder_id not in parent:
                    parent.update({folder_id: {'name': name}})
                else:
                    parent.get(folder_id).update({'name': name})
            return data

    def mv(self, src: int, dest: int) -> bool:
        """
        move file to directory by id, without renaming
        :param src: file to be moved, file id as int
        :param dest: destination directory, directory id as int
        :return: True or None
        """
        url = 'https://webapi.115.com/files/move'
        result = self.s.post(url, data={'pid': dest, 'fid[0]': src}, headers={'Origin': origin['webapi'], 'Referer': referer['115'].format(self.default_dir)}).json()
        if result['errno'] == '':
            _ = functools.reduce(dict.__getitem__, self._dirs_lookup[src], self.dirs)  # TODO: need to test
            self._dirs_lookup[src] = self._dirs_lookup[dest].append(dest)
            parent = functools.reduce(dict.__getitem__, self._dirs_lookup[src], self.dirs)
            if src not in parent:
                parent.update({src: _})
            else:
                parent.get(src).update(_)
            return True

    def ren(self, src: int, new_name: str) -> bool:
        """
        rename a file
        :param src: file to be renamed, file id as int
        :param new_name: new filename as string
        :return: True or None
        """
        url = 'https://webapi.115.com/files/edit'
        result = self.s.post(url, data={'fid': src, 'file_name': new_name}, headers={'Origin': origin['webapi'], 'Referer': referer['115'].format(self.default_dir)}).json()
        if result['errno'] == '':
            if src in self._dirs_lookup:  # TODO: need to test
                functools.reduce(dict.__getitem__, self._dirs_lookup[src], self.dirs).update(name=new_name)
            return True

    def mkdir(self, pwd: int, new_name: str) -> bool:
        """
        create new directory
        :param pwd: current directory, directory id as int
        :param new_name: new directory name as string
        :return: True or None
        """
        url = 'https://webapi.115.com/files/add'
        result = self.s.post(url, data={'pid': pwd, 'cname': new_name}, headers={'Origin': origin['webapi'], 'Referer': referer['115'].format(self.default_dir)}).json()
        '''{"state":true,"error":"","errno":"","aid":1,"cid":"1173956375760499041","cname":"Anime",
        "file_id":"1173956375760499041","file_name":"Anime"}'''
        if result['errno'] == '':
            folder_id = result['cid']
            if pwd == 0:
                self._dirs_lookup[folder_id] = [0]
            else:
                self._dirs_lookup[folder_id] = self._dirs_lookup[pwd] + [pwd]  # TODO: pwd not in lookup
            parents = self._dirs_lookup[folder_id]
            functools.reduce(dict.__getitem__, parents, self.dirs).update({folder_id: {'name': result['file_name']}})
            return True

    def rm(self, pwd: int, target: int) -> bool:
        """
        remove a file
        :param pwd: current directory, directory id as int
        :param target: file to be removed, file id as int
        :return: True or None
        """
        url = 'https://webapi.115.com/rb/delete'
        result = self.s.post(url, data={'pid': pwd, 'fid[0]': target}, headers={'Origin': origin['webapi'], 'Referer': referer['115'].format(self.default_dir)}).json()
        if result['errno'] == '':
            if target in self._dirs_lookup:
                functools.reduce(dict.__getitem__, self._dirs_lookup[target], self.dirs).pop(target)
                del self._dirs_lookup[target]
            return True

    def add_magnet(self, link: str) -> bool:
        """
        add a magnet link to task
        :param link: magnet link in string
        :return: True or None
        """
        url = 'https://115.com/web/lixian/?ct=lixian&ac=add_task_url'
        result = self.s.post(url, data={'url': link, 'uid': self.uid, 'sign': self.sign, 'time': self.time},
                             headers={'Origin': origin['115'], 'Referer': referer['115'].format(self.default_dir)}
                             ).json()
        '''{"info_hash":"186e2e8f981ab9877f12c6031e9c0ff080e30bff","name":"","state":true,"errno":0,"errtype":"suc",
        "url":"magnet:?xt=urn:btih:DBXC5D4YDK4YO7YSYYBR5HAP6CAOGC77\u0026dn=\u0026tr...","errcode":0}'''
        if result['errno'] == 0:
            return True

    def ls_task(self, page: int = 1) -> list:
        """
        list all tasks starting from page
        :param page: start page number as int
        :return: list of dict: [{
            "info_hash": "186e2e8f981ab9877f12c6031e9c0ff080e30bff",
            "add_time": 1509943176,
            "percentDone": 0,
            "size": 223092533,
            "peers": 0,
            "rateDownload": 0,
            "name": "[DMG][Imouto sae Ireba Ii.][01][1080P][BIG5].mp4",
            "last_update": 1509943628,
            "left_time": 0,
            "file_id": "",
            "move": 0,
            "status": 0,
            "url": "magnet:?xt=urn:btih:DBXC5D4YDK4YO7YSYYBR5HAP6CAOGC77\u0026dn=\u0026tr=...",
            "del_path": ""
        }]
        """
        url = 'https://115.com/web/lixian/?ct=lixian&ac=task_lists'
        data = {'page': page, 'uid': self.uid, 'sign': self.sign, 'time': self.time}
        result = self.s.post(url,
                             data=data,
                             headers={'Origin': origin['115'], 'Referer': referer['115'].format(self.default_dir)}
                             ).json()
        data = result['tasks']
        if result['errtype'] != 'suc':
            return []
        if result['page'] != result['page_count']:
            data.append(self.ls_task(page+1))
        return data

    def get_link(self, pickcode: str) -> str:
        """
        get download link from pickcode
        :param pickcode: pickcode as string
        :return: download url
        """
        result = self._get_link(pickcode).json()
        if result['msg_code'] == 0:
            return result['file_url']

    def _get_link(self, pickcode: str) -> requests.Response:
        # url = "https://115.com/"
        # self.s.get(url,
        #            params={'ct': 'download', 'ac': 'index', 'pickcode': pickcode, '_t': int(time.time() * 1e3)},
        #            headers={'Referer': referer['115'].format(self.default_dir)})
        url = 'https://webapi.115.com/files/download'
        result = self.s.get(url, params={'pickcode': pickcode, '_': int(time.time() * 1e3)}, headers={'Referer': referer['115'].format(self.default_dir)})
        '''{"state":true,"msg":"","msg_code":0,"is_115chrome":0,"is_snap":0,"is_vip":1,"file_name":"[DMG][Imout
        o sae Ireba Ii.][01][1080P][BIG5].mp4","file_size":"223092533","pickcode":"dfrlfx4e1ote8x5tj","file_id"
        :"1173954155581173992","user_id":362421191,"file_url":"https:\/\/fscdntel-vip.115.com\/files\/c210\/1\/
        vCuspkyyDj57s1C3LjpS2nAmfKnn4DwoH2dMHhaO\/%5BDMG%5D%5BImouto%20sae%20Ireba%20Ii.%5D%5B01%5D%5B1080P%5D%
        5BBIG5%5D.mp4?t=1509974436&u=vip-3063327692-362421191-dfrlfx4e1ote8x5tj&s=13107200&k=wHLarKiQC5EhpVJ1ZLIJEg"}'''
        return result

    def get_url(self, path: str) -> str:
        """
        get download link from absolute path
        :param path: abs path
        :return: download url
        """
        return self.get_link(self.path[path]['pickcode'])


if __name__ == '__main__':
    x115 = Connect115()
