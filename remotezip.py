"""ネット上の zip から必要なファイルだけを取り出す(全体をダウンロードしない)。
HTTP の Range 要求で、中身の一覧と選んだファイルの部分だけを読む。"""
import io
import os
import shutil
import struct
import urllib.request
import zipfile

_BLOCK = 8 << 20  # 先読みの単位(連続したファイルをまとめて取得して要求回数を減らす)


class HttpFile(io.RawIOBase):
    def __init__(self, url, block=_BLOCK):
        self._block = block
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            self.url, self.size = r.url, int(r.headers["Content-Length"])
        self._pos, self._buf, self._buf_at = 0, b"", -1

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=0):
        self._pos = offset if whence == 0 else self._pos + offset if whence == 1 else self.size + offset
        return self._pos

    def _fetch(self, start, end):
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end - 1}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self._pos
        n = min(n, self.size - self._pos)
        if n <= 0:
            return b""
        out = bytearray()
        while n > 0:
            if not (self._buf_at <= self._pos < self._buf_at + len(self._buf)):
                end = min(self.size, self._pos + max(n, self._block))
                self._buf, self._buf_at = self._fetch(self._pos, end), self._pos
            i = self._pos - self._buf_at
            chunk = self._buf[i:i + n]
            out += chunk
            self._pos += len(chunk)
            n -= len(chunk)
        return bytes(out)


class _Slice(io.RawIOBase):
    """大きなファイルの一部分を、独立したファイルとして見せる(zip の中の zip を読むため)。"""

    def __init__(self, f, offset, size):
        self._f, self._off, self.size, self._pos = f, offset, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=0):
        self._pos = offset if whence == 0 else self._pos + offset if whence == 1 else self.size + offset
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0 or self._pos + n > self.size:
            n = self.size - self._pos
        if n <= 0:
            return b""
        self._f.seek(self._off + self._pos)
        data = self._f.read(n)
        self._pos += len(data)
        return data


def open_zip(url, block=_BLOCK):
    """block: 先読みの大きさ。目次だけ読むときは小さくする。"""
    f = HttpFile(url, block)
    return zipfile.ZipFile(f), f


def inner_zip(zf, raw, info):
    """無圧縮で格納された zip の中の zip を開く。"""
    raw.seek(info.header_offset)
    head = raw.read(30)
    name_len, extra_len = struct.unpack("<HH", head[26:30])
    return zipfile.ZipFile(_Slice(raw, info.header_offset + 30 + name_len + extra_len, info.compress_size))


def extract(zf, members, dest, progress, strip=""):
    """members を dest へ取り出す。途中で止まっても、取り出し済みのファイルは飛ばして再開する。"""
    total = sum(m.compress_size for m in members) or 1  # 実際に通信する量で進み具合を出す
    done = 0
    for m in members:
        name = m.filename[len(strip):] if strip and m.filename.startswith(strip) else m.filename
        path = os.path.join(dest, *name.split("/"))
        if m.is_dir():
            os.makedirs(path, exist_ok=True)
            continue
        if not (os.path.exists(path) and os.path.getsize(path) == m.file_size):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with zf.open(m) as src, open(path + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(path + ".part", path)
        done += m.compress_size
        progress(done / total, f"ダウンロード中 {done >> 20} / {total >> 20} MB")
