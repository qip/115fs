import os
import sys
import time
import math
import errno
import shutil
from x115 import Connect115
from fuse import FUSE, FuseOSError, Operations  # pip install fusepy


class X115FS(Operations):
    def __init__(self, x115, buffer, tmp_dir, retain):
        self.x115 = x115
        self.buffer = buffer
        self.tmp = tmp_dir  # os.path.join(os.getcwd(), tmp_dir)
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass
        try:
            os.mkdir(self.tmp)
        except Exception:
            pass
        self.retain = retain
        self.fd = {}
        self._fd = 0
        self.opened_path = {}  # path=fd
        self.last_read_fh = {}  # fh={time, path}
        self.last_read_time = {}  # time=fh
        self.uid = os.getuid()
        self.gid = os.getgid()
        self.log(self.x115.path)

    def log(self, *args, **kwargs):
        print(*args, **kwargs)
        now = time.time() - self.retain
        for i in sorted(self.last_read_time):
            if i < now:
                fh = self.last_read_time[i]
                f = self.fd[fh]['buffer']
                f.close()
                os.remove(f.name)
                del self.fd[fh]
                del self.opened_path[self.last_read_fh[fh]['path']]
                del self.last_read_fh[fh]
                del self.last_read_time[i]
            else:
                break

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        self.log('access', path, mode)
        if mode & os.W_OK:
            raise FuseOSError(errno.EACCES)
        elif not self.x115.path[path]:
            raise FuseOSError(errno.ENOENT)

    def getattr(self, path, fh=None):
        self.log('getattr', path, fh)
        f = self.x115.path[path]
        # self.log(f)
        if f:
            if 'cid'in f:  # is dir
                mode = 0o0040555
                size = len(f)
            else:  # is file
                mode = 0o0100444
                size = f['size']
            result = {
                'st_gid': self.gid,
                'st_uid': self.uid,
                'st_nlink': 1,
                'st_mode': mode,
                'st_ctime': f['time'],  # create time
                'st_atime': f['time'],  # access time
                'st_mtime': f['time'],  # modify time
                'st_size': size
            }
            return result
        else:
            raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        self.log('readdir', path, fh)
        dirents = ['.', '..']
        node = self.x115.path[path]
        if node and 'cid' in node:
            dirents.extend(self.x115.listdir(path))
        for r in dirents:
            yield r

    def statfs(self, path):
        self.log('statfs', path)
        fs = self.x115.fs()
        return {
            'f_bavail': math.ceil(fs['free'] / 4096),
            'f_bfree': math.ceil(fs['free'] / 4096),
            'f_blocks': math.ceil(fs['total'] / 4096),
            'f_bsize': 4096,
            'f_frsize': 4096,
            'f_favail': 1000000000,
            'f_ffree': 1000000000,
            'f_files': 1000000000,
            'f_flag': os.ST_RDONLY & os.ST_NOSUID & os.ST_NOEXEC & os.ST_NOATIME,
            'f_namemax': 255
        }

    def rename(self, old, new):
        self.log('rename', old, new)
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path):
        self.log('rmdir', path)
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path, mode):
        self.log('mrdir', path, mode)
        raise FuseOSError(errno.EROFS)

    def chmod(self, path, mode):
        self.log('chmod', path, mode)
        raise FuseOSError(errno.EROFS)
        # raise FuseOSError(errno.EPERM)

    def chown(self, path, uid, gid):
        self.log('chown', path, uid, gid)
        raise FuseOSError(errno.EROFS)
        # raise FuseOSError(errno.EPERM)

    def symlink(self, name, target):
        self.log('symlink', name, target)
        raise FuseOSError(errno.EROFS)

    def link(self, target, name):
        self.log('link', target, name)
        raise FuseOSError(errno.EROFS)

    def unlink(self, path):
        self.log('unlink', path)
        raise FuseOSError(errno.EROFS)

    def readlink(self, path):
        self.log('readlink', path)
        raise FuseOSError(errno.EINVAL)

    def mknod(self, path, mode, dev):
        self.log('mknod', path, mode, dev)
        raise FuseOSError(errno.EROFS)

    def utimens(self, path, times=None):
        self.log('utimens', path, times)
        raise FuseOSError(errno.EROFS)

    # File methods
    # ============

    def open(self, path, flags):
        self.log('open', path, flags)
        if flags & os.O_WRONLY:  # TODO: proper permission
            raise FuseOSError(errno.EROFS)
        f = self.x115.path[path]
        if not f:
            raise FuseOSError(errno.ENOENT)
        if path in self.opened_path:
            fh = self.opened_path[path]
            if fh in self.last_read_fh:
                t = self.last_read_fh[fh]
                del self.last_read_time[t['time']]
                del self.last_read_fh[fh]
            # self.fd[fh]['buffer'] = open(os.path.join(self.tmp, str(fh)), 'w+b')
            return fh
        self._fd += 1
        url = self.x115.get_url(path).replace('http://', 'https://')
        self.fd[self._fd] = {
            'path': path,
            'size': f['size'],
            'url': url,
            'buffer': open(os.path.join(self.tmp, str(self._fd)), 'w+b'),
            'range': [],
            'headers': {'Accept-Encoding': '*'}
        }
        self.opened_path[path] = self._fd
        return self._fd

    def read(self, path, length, offset, fh):
        self.log('read', path, length, offset, fh)
        blk1, o1 = divmod(offset, self.buffer)
        blk2, o2 = divmod(offset+length, self.buffer)
        for blk in range(blk1, blk2 + 1):  # one extra buffer
            if blk not in self.fd[fh]['range']:
                self._read(blk * self.buffer, fh)
                self.fd[fh]['range'].append(blk)
        f = self.fd[fh]['buffer']
        f.seek(offset)
        return f.read(length)

    def _read(self, offset, fh):
        self.log('_read', offset, fh)
        if offset > self.fd[fh]['size']:
            return
        if offset == 0 and self.buffer >= self.fd[fh]['size']:
            if 'Range' in self.fd[fh]['headers']:
                del self.fd[fh]['headers']['Range']
        else:
            end = offset + self.buffer - 1
            if end >= self.fd[fh]['size']:
                end = ''
            self.fd[fh]['headers'].update({'Range': f'bytes={offset}-{end}'})
        r = self.x115.s.get(self.fd[fh]['url'], headers=self.fd[fh]['headers'], stream=True)
        self.log(r, self.fd[fh]['headers'], r.headers)
        f = self.fd[fh]['buffer']
        f.seek(offset)
        for chunk in r.iter_content(chunk_size=4096):
            if chunk:
                f.write(chunk)

    def release(self, path, fh):
        self.log('release', path, fh)
        now = time.time()
        if now in self.last_read_time:
            now = sorted(self.last_read_time)[-1] + 1
        self.last_read_time[now] = fh
        self.last_read_fh[fh] = {'time': now, 'path': path}
        # f = self.fd[fh]['buffer']
        # f.close()
        # os.remove(f.name)
        # del self.fd[fh]

    def create(self, path, mode, fi=None):
        self.log('create', path, mode, fi)
        raise FuseOSError(errno.EROFS)

    def write(self, path, buf, offset, fh):
        self.log('write', path, buf, offset, fh)
        raise FuseOSError(errno.EROFS)

    def truncate(self, path, length, fh=None):
        self.log('truncate', path, length, fh)
        raise FuseOSError(errno.EROFS)

    def flush(self, path, fh):
        self.log('flush', path, fh)
        f = self.fd[fh]['buffer']
        f.flush()
        # raise FuseOSError(errno.EROFS)

    def fsync(self, path, fdatasync, fh):
        self.log('fsync', path, fdatasync, fh)
        raise FuseOSError(errno.EROFS)


def main(mountpoint):
    x115 = Connect115()
    FUSE(X115FS(x115, buffer=10 * 1024 ** 2, tmp_dir='tmp', retain=10 * 60), mountpoint, nothreads=True, foreground=True, allow_other=True, fsname='115')


if __name__ == '__main__':
    main(sys.argv[1])
