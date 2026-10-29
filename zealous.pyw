"""ダブルクリックで起動(コンソール画面なし)。"""
import multiprocessing as mp
import os
import sys

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.getcwd())
    mp.freeze_support()
    from app import App
    App().mainloop()
