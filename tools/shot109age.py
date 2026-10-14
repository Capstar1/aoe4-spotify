"""1.0.9 test copy (copy of real settings, temp APPDATA): screenshot main panel (+ Age Intros) client area via PrintWindow.
usage: shot109.py SRC OUTPREFIX SCALE"""
import os, sys, tempfile, shutil, tkinter, ctypes
from ctypes import wintypes as wt
src, pre, sc = sys.argv[1], sys.argv[2], float(sys.argv[3])
tmp = tempfile.mkdtemp(prefix="aoe4cmp_"); shutil.copytree(os.path.join(os.environ["APPDATA"], "AoE4Spotify"), os.path.join(tmp, "AoE4Spotify"))
os.environ["APPDATA"] = tmp; os.environ["AOE4SPOTIFY_MUTEX_SUFFIX"] = "_cmp%d" % os.getpid(); os.environ["AOE4SPOTIFY_PANEL_OPEN"] = "1"
sys.path.insert(0, src)
from PIL import Image
u = ctypes.windll.user32; g = ctypes.windll.gdi32
def grab(hwnd, path):
    r = wt.RECT(); u.GetClientRect(hwnd, ctypes.byref(r)); w, h = r.right, r.bottom
    wr = wt.RECT(); u.GetWindowRect(hwnd, ctypes.byref(wr)); pt = wt.POINT(0, 0); u.ClientToScreen(hwnd, ctypes.byref(pt))
    ox, oy = pt.x - wr.left, pt.y - wr.top; W, H = wr.right - wr.left, wr.bottom - wr.top
    hdc = u.GetDC(hwnd); mdc = g.CreateCompatibleDC(hdc); bm = g.CreateCompatibleBitmap(hdc, W, H); g.SelectObject(mdc, bm)
    u.PrintWindow(hwnd, mdc, 2)
    buf = ctypes.create_string_buffer(W * H * 4)
    class BIH(ctypes.Structure): _fields_ = [("a", wt.DWORD), ("w", wt.LONG), ("h", wt.LONG), ("p", wt.WORD), ("b", wt.WORD), ("c", wt.DWORD), ("s", wt.DWORD), ("x", wt.LONG), ("y", wt.LONG), ("u", wt.DWORD), ("i", wt.DWORD)]
    bi = BIH(40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0); g.GetDIBits(mdc, bm, 0, H, buf, ctypes.byref(bi), 0)
    im = Image.frombuffer("RGBA", (W, H), buf, "raw", "BGRA", 0, 1).convert("RGB")
    im.crop((ox, oy, ox + w, oy + h)).save(path); g.DeleteObject(bm); g.DeleteDC(mdc); u.ReleaseDC(hwnd, hdc)
    print(path, w, h)
_init = tkinter.Tk.__init__
def init(self, *a, **k):
    _init(self, *a, **k); self.tk.call("tk", "scaling", sc * 96 / 72)
tkinter.Tk.__init__ = init
_ml = tkinter.Misc.mainloop
def ml(self, n=0):
    root = self
    if not hasattr(root, "_press"): return _ml(self, n)
    root.geometry("+200+100")
    def hw(w): return u.GetParent(w.winfo_id()) or w.winfo_id()
    def s1(): grab(hw(root), pre + "_main.png"); root._press("intro"); root.after(1200, s2)
    def canv(w):
        for c in w.winfo_children():
            if isinstance(c, tkinter.Canvas) and c.winfo_width() > 480 * sc: return c
            r = canv(c)
            if r: return r
    def s2():
        cv = canv(root); S = sc; x, y = int(200 * S), int((124 + 3 * 106 + 30) * S)
        cv.event_generate("<Motion>", x=x, y=y); cv.event_generate("<ButtonPress-1>", x=x, y=y); cv.event_generate("<ButtonRelease-1>", x=x, y=y)
        root.after(1500, s3)
    def s3(): grab(hw(root), pre + "_age.png"); root.after(100, root.destroy)
    root.after(2500, s1)
    return _ml(self, n)
tkinter.Misc.mainloop = ml
import aoe4_spotify as a
a.panel()
