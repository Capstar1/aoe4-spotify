import ctypes
from ctypes import wintypes as wt
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

