"""ビルド確認用: 動作確認の画面写真を、ログで見られる形(JPEG の base64)で書き出す。"""
import base64
import glob
import io
import os
import sys

from PIL import Image

for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.png"))):
    b = io.BytesIO()
    Image.open(f).convert("RGB").save(b, "JPEG", quality=70)
    print("IMG", os.path.basename(f), base64.b64encode(b.getvalue()).decode())
