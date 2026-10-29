"""Zealous を1つだけ起動させる。2つ目を起動しようとしたら、1つ目に「表に出て」と伝えて終わる。
PC内だけで使う通信口(127.0.0.1 の決まった番号)を「起動中の印」として使う。"""
import socket
import threading

PORT = 47391
_MESSAGE = b"zealous:show"


def acquire():
    """起動中の印を取る。取れたら受付用のソケット、すでに起動中なら None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORT))
    except OSError:
        s.close()
        return None
    s.listen(4)
    return s


def notify_running():
    """起動中の Zealous に、ウィジェットを表に出すよう伝える。"""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as c:
            c.sendall(_MESSAGE)
    except OSError:
        pass


def serve(sock, on_show):
    """2つ目の起動からの知らせを待ち、届いたら on_show() を呼ぶ(裏で動く)。"""
    def loop():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with conn:
                try:
                    if conn.recv(64) == _MESSAGE:
                        on_show()
                except OSError:
                    pass
    threading.Thread(target=loop, daemon=True).start()
