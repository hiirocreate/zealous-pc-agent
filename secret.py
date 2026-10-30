"""パスワードなどを、このPCのこのユーザーだけが読める形で保存する(Windows の DPAPI)。
設定ファイルには暗号化した文字だけが入り、別のPCや別のユーザーでは元に戻せない。"""
import base64
import os

PREFIX = "dpapi:"


def _blob(data):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    return BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf, BLOB


def _call(func_name, data):
    import ctypes
    blob_in, keep, BLOB = _blob(data)
    blob_out = BLOB()
    func = getattr(ctypes.windll.crypt32, func_name)
    if func_name == "CryptProtectData":
        ok = func(ctypes.byref(blob_in), "Zealous", None, None, None, 0x01, ctypes.byref(blob_out))
    else:
        ok = func(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise OSError("暗号化に失敗しました")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect(text):
    """平文 → 保存用の文字。空ならそのまま空。"""
    if not text:
        return ""
    data = text.encode("utf-8")
    if os.name == "nt":
        data = _call("CryptProtectData", data)
    return PREFIX + base64.b64encode(data).decode()


def reveal(stored):
    """保存用の文字 → 平文。読めなければ空。"""
    if not stored or not str(stored).startswith(PREFIX):
        return stored or ""
    try:
        data = base64.b64decode(stored[len(PREFIX):])
        if os.name == "nt":
            data = _call("CryptUnprotectData", data)
        return data.decode("utf-8")
    except Exception:
        return ""
