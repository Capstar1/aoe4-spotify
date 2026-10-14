"""Shared window helpers: app icon, glass tooltips, pens, mosaics, edit menu.

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import os, re, time
from aoe4spotify.core.runtime import ASSETS, log
from aoe4spotify.core.settings import custom_cover
from aoe4spotify.core.ui.library import COVERS, track_cover

def app_badge(px):
    """The app icon (green circle, "IV") as a PIL image: largest frame of the bundled app.ico, else drawn like make_icon.py."""
    from PIL import Image, ImageDraw
    try:
        ico = Image.open(os.path.join(ASSETS, "assets", "app.ico")); ico.size = max(ico.info.get("sizes") or [ico.size])
        return ico.convert("RGBA").resize((px, px), Image.LANCZOS)
    except Exception: pass
    ss = 8; N = px * ss; k = N / 1024; ox, oy, w = 0.409, -0.5, 92
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([16 * k, 16 * k, N - 16 * k, N - 16 * k], fill="#1DB954")
    for pts in ([(310, 320), (310, 704)], [(490, 320), (620, 704), (750, 320)]):
        P = [((x + ox) * k, (y + oy) * k) for x, y in pts]; r = w * k / 2
        for a, b in zip(P, P[1:]): d.line([a, b], fill="#191414", width=int(w * k))
        for x, y in P: d.ellipse([x - r, y - r, x + r, y + r], fill="#191414")
    return im.resize((px, px), Image.LANCZOS)
def set_app_icon(win):
    """Title-bar icon = app.ico (bundled), so it matches the exe and shortcuts."""
    ico = os.path.join(ASSETS, "assets", "app.ico")
    try:
        if os.path.exists(ico): win.iconbitmap(ico); win.iconbitmap(default=ico); return
    except Exception as e: log("Icon: %r" % e)
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk
class GlassTip:
    """Dark glass tooltip card with an arrow, in its own layered top-level window (never clipped, per-pixel alpha
    for smooth corners + soft shadow on Windows). Anchored to an element's screen rectangle, flips above/below so it
    never covers it, clamped to that monitor's work area. 350 ms delay, instant switch between neighbours,
    120 ms fade + 2 px slide in, 80 ms fade out. One per Tk root: get_tip(widget)."""
    DELAY, WARM, FIN, FOUT, MAXW, PAD, SH = 350, 400, 120, 80, 260, 10, 12
    def __init__(self, root):
        import tkinter as tk
        self.root = root; self.w = tk.Toplevel(root, bg="#010203"); self.w.withdraw(); self.w.overrideredirect(True)
        self.key = None; self.want = None; self.job = None; self.anim = None; self.shown = False; self.t_hide = 0.0
        self.hwnd = None; self.layered = False; self.img = None; self.pos = (0, 0); self.label = None
        self.wd = None; self.cursor = None; self.foreground = None     # (tests may override cursor / foreground)
        try: self._init_layered()
        except Exception as ex: log("Tooltip: layered window unavailable (%r)" % ex)
        if not self.layered:
            self.label = tk.Label(self.w, bd=0, highlightthickness=0, bg="#010203"); self.label.pack()
            try: self.w.attributes("-transparentcolor", "#010203")
            except Exception: pass
        b = root.bind_all
        for ev in ("<ButtonPress>", "<MouseWheel>", "<KeyPress>"): b(ev, lambda e: self.hide(), add="+")
    # -- Windows layered window
    def _init_layered(self):
        import ctypes
        if os.name != "nt": return
        self.w.update_idletasks(); self._ensure_layered(); self.layered = True
    def _ensure_layered(self):
        """(Re)apply the layered style to the CURRENT wrapper window. Tk recreates the wrapper HWND on some wm
        changes (e.g. `wm transient` to a new owner): the new one is a plain window that shows as an empty
        light-grey box and ignores UpdateLayeredWindow. Called before every show."""
        import ctypes
        u = ctypes.windll.user32; self.w.update_idletasks()
        h = u.GetParent(self.w.winfo_id()) or self.w.winfo_id()
        GWL_EXSTYLE = -20; ex = u.GetWindowLongW(h, GWL_EXSTYLE); want = 0x80000 | 0x20 | 0x08000000 | 0x80   # LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW
        if ex & want != want: u.SetWindowLongW(h, GWL_EXSTYLE, ex | want)
        self.hwnd = h
    def _push(self, alpha):
        """Blit self.img (RGBA) at self.pos with overall alpha 0..1."""
        x, y = self.pos
        if not self.layered:
            self.w.geometry("+%d+%d" % (x, y))
            try: self.w.attributes("-alpha", max(0.0, min(1.0, alpha)))
            except Exception: pass
            return
        import ctypes
        from ctypes import wintypes as wt
        im = self.img; wd, ht = im.size
        r, g, b, a = im.split()
        from PIL import ImageChops
        pm = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a))   # premultiplied BGRA
        data = pm.tobytes()
        u, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        class BLEND(ctypes.Structure):
            _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]
        bih = BIH(ctypes.sizeof(BIH), wd, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
        sdc = u.GetDC(0); mdc = g32.CreateCompatibleDC(sdc); bits = ctypes.c_void_p()
        g32.CreateDIBSection.restype = ctypes.c_void_p
        hb = g32.CreateDIBSection(mdc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data)); old = g32.SelectObject(mdc, ctypes.c_void_p(hb))
            pt = wt.POINT(x, y); sz = wt.SIZE(wd, ht); src = wt.POINT(0, 0)
            bl = BLEND(0, 0, int(255 * max(0.0, min(1.0, alpha))), 1)
            u.UpdateLayeredWindow(wt.HWND(self.hwnd), sdc, ctypes.byref(pt), ctypes.byref(sz), mdc, ctypes.byref(src), 0, ctypes.byref(bl), 2)
            g32.SelectObject(mdc, old)
        finally:
            g32.DeleteObject(ctypes.c_void_p(hb)); g32.DeleteDC(mdc); u.ReleaseDC(0, sdc)
    # -- rendering
    @staticmethod
    def _font(px, bold):
        for f in (("seguisb.ttf" if bold else "segoeui.ttf"), "segoeui.ttf", "arial.ttf"):
            try: return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts", f), px)
            except Exception:
                try: return ImageFont.truetype(f, px)
                except Exception: pass
        return ImageFont.load_default()
    def _lines(self, text, fnt, maxw):
        """Wrap to max 2 lines; ellipsize the rest."""
        words = str(text).split(); lines = []; cur = ""
        for w_ in words:
            t_ = (cur + " " + w_).strip()
            if fnt.getlength(t_) <= maxw or not cur: cur = t_
            else: lines.append(cur); cur = w_
        if cur: lines.append(cur)
        if len(lines) > 2: lines = [lines[0], " ".join(lines[1:])]
        out = []
        for ln in lines:
            if fnt.getlength(ln) > maxw:
                while ln and fnt.getlength(ln + "\\u2026") > maxw: ln = ln[:-1]
                ln = ln.rstrip() + "\\u2026"
            out.append(ln)
        return out or [""]
    def _render(self, text, scale, arrow_up, ax):
        Q = 3; s = scale; pad, sh = int(self.PAD * s), int(self.SH * s)
        fnt = self._font(int(12 * s * Q), True)
        lines = self._lines(text, self._font(int(12 * s), True), self.MAXW * s)
        lh = int(17 * s); tw = max(int(self._font(int(12 * s), True).getlength(l)) for l in lines)
        cw, chh = tw + 2 * pad + int(4 * s), lh * len(lines) + int(14 * s); ah = int(6 * s)
        W_, H_ = cw + 2 * sh, chh + ah + 2 * sh
        cy0 = sh + (ah if arrow_up else 0)
        ax = max(sh + int(14 * s), min(W_ - sh - int(14 * s), ax))
        def shape(d, k, fill):
            d.rounded_rectangle([sh * k, cy0 * k, (sh + cw) * k, (cy0 + chh) * k], int(8 * s * k), fill=fill)
            if arrow_up: d.polygon([((ax - ah) * k, (cy0 + 1) * k), ((ax + ah) * k, (cy0 + 1) * k), (ax * k, (cy0 - ah) * k)], fill=fill)
            else: d.polygon([((ax - ah) * k, (cy0 + chh - 1) * k), ((ax + ah) * k, (cy0 + chh - 1) * k), (ax * k, (cy0 + chh + ah) * k)], fill=fill)
        shd = Image.new("L", (W_, H_), 0); shape(ImageDraw.Draw(shd), 1, 120)
        shd = shd.filter(ImageFilter.GaussianBlur(5 * s)); shd = ImageChops_offset(shd, 0, int(3 * s))
        im = Image.new("RGBA", (W_ * Q, H_ * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        shape(d, Q, (255, 255, 255, 30))                                  # hairline edge
        inner = Image.new("RGBA", im.size, (0, 0, 0, 0)); di = ImageDraw.Draw(inner)
        di.rounded_rectangle([(sh * Q) + Q, cy0 * Q + Q, (sh + cw) * Q - Q, (cy0 + chh) * Q - Q], int(8 * s * Q) - Q, fill=(36, 36, 38, 246))
        if arrow_up: di.polygon([((ax - ah) * Q + Q, (cy0 + 1) * Q + Q), ((ax + ah) * Q - Q, (cy0 + 1) * Q + Q), (ax * Q, (cy0 - ah) * Q + 2 * Q)], fill=(36, 36, 38, 246))
        else: di.polygon([((ax - ah) * Q + Q, (cy0 + chh - 1) * Q - Q), ((ax + ah) * Q - Q, (cy0 + chh - 1) * Q - Q), (ax * Q, (cy0 + chh + ah) * Q - 2 * Q)], fill=(36, 36, 38, 246))
        im.alpha_composite(inner)
        for i, ln in enumerate(lines):
            d.text(((sh + cw / 2) * Q, (cy0 + int(7 * s) + lh * i + lh / 2) * Q), ln, font=fnt, fill=(242, 242, 242, 255), anchor="mm")
        im = im.resize((W_, H_), Image.LANCZOS)
        base = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); base.putalpha(shd); base.alpha_composite(im)
        if not self.layered:                                              # fallback: no translucency, key colour background
            flat = Image.new("RGB", (W_, H_), (1, 2, 3)); m = im.split()[3].point(lambda v: 255 if v > 90 else 0)
            flat.paste(im.convert("RGB"), (0, 0), m); base = flat
        return base, sh, cy0, chh, ah
    # -- monitor work area for a point (multi-monitor aware)
    def _work(self, x, y):
        try:
            import ctypes
            from ctypes import wintypes as wt
            class MI(ctypes.Structure): _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
            u = ctypes.windll.user32; u.MonitorFromPoint.restype = ctypes.c_void_p
            hm = u.MonitorFromPoint(wt.POINT(int(x), int(y)), 2); mi = MI(); mi.cbSize = ctypes.sizeof(MI)
            if u.GetMonitorInfoW(ctypes.c_void_p(hm), ctypes.byref(mi)):
                r = mi.rcWork; return r.left, r.top, r.right, r.bottom
        except Exception: pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
    # -- public
    # -- watchdog: the tooltip may only exist while the pointer is on its anchor in our foreground window
    def _ptr(self):
        if self.cursor: return self.cursor()
        try:
            import ctypes
            from ctypes import wintypes as wt
            pt = wt.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)); return pt.x, pt.y
        except Exception: return self.root.winfo_pointerxy()
    def _ours_fg(self):
        if self.foreground: return self.foreground()
        try:
            import ctypes
            from ctypes import wintypes as wt
            u = ctypes.windll.user32
            u.GetForegroundWindow.restype = wt.HWND
            u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
            fg = u.GetForegroundWindow()
            if not fg: return False
            pid = wt.DWORD(); u.GetWindowThreadProcessId(fg, ctypes.byref(pid)); return pid.value == os.getpid()
        except Exception as ex:
            log("Tooltip: foreground check failed (%r)" % ex); return False          # unsure -> hide
    def ok(self):
        """Still valid to show: anchor alive + mapped, owner not minimised, our window in front, pointer on the anchor."""
        if not self.want: return False
        _, _, (x0, y0, x1, y1), _, w = self.want
        try:
            if w is not None:
                if not w.winfo_exists() or not w.winfo_viewable(): return False
                if w.winfo_toplevel().state() in ("iconic", "withdrawn"): return False
            if not self._ours_fg(): return False
            px, py = self._ptr()
            return x0 - 2 <= px <= x1 + 2 and y0 - 2 <= py <= y1 + 2
        except Exception: return False
    def _visible(self):
        try: return bool(self.w.winfo_viewable())
        except Exception: return False
    def _watch(self):
        self.wd = None
        if not (self.shown or self.job or self._visible()): return
        if (self.shown or self.job) and not self.ok(): self.hide()
        elif not (self.shown or self.job or self.anim): self._gone()          # visible but nothing owns it: remove
        self.wd = self.root.after(100, self._watch)
    def _gone(self):
        """Withdraw for sure (no fade), cancel timers."""
        for j in ("job", "anim"):
            if getattr(self, j):
                try: self.root.after_cancel(getattr(self, j))
                except Exception: pass
                setattr(self, j, None)
        self.shown = False
        try: self.w.withdraw()
        except Exception: pass
    def request(self, key, text, rect, scale=1.0, widget=None):
        """Ask for a tooltip for `key` anchored to screen rect (x0, y0, x1, y1) of `widget`."""
        if not text: self.hide(); return
        if key == self.key and (self.shown or self.job): self.want = (key, text, rect, scale, widget); return
        fading = bool(self.anim) and not self.shown
        self._cancel(); self.key = key; self.want = (key, text, rect, scale, widget)
        if fading and self._visible(): self._gone()           # a cancelled fade-out must not leave the card behind
        if not self.ok(): self.want = None; self.key = None; self._gone(); return
        if not self.wd: self.wd = self.root.after(100, self._watch)
        warm = self.shown or (time.time() - self.t_hide) * 1000 < self.WARM
        if warm: self._show(slide=False)
        else: self.job = self.root.after(self.DELAY, lambda: self._show(slide=True))
    def _cancel(self):
        for j in ("job", "anim"):
            if getattr(self, j):
                try: self.root.after_cancel(getattr(self, j))
                except Exception: pass
                setattr(self, j, None)
    def _show(self, slide=True):
        self.job = None
        if not self.want: return
        if not self.ok(): self.want = None; self.key = None; self._gone(); return   # re-check hover right before showing
        key, text, (x0, y0, x1, y1), s, _w = self.want
        try:
            if not self.w.winfo_exists(): return
            wx0, wy0, wx1, wy1 = self._work((x0 + x1) / 2, (y0 + y1) / 2)
            gap = int(6 * s)
            probe, sh, cy0, chh, ah = self._render(text, s, True, 0)
            W_, H_ = probe.size
            below = y1 + gap + H_ - sh <= wy1                        # flip above when there is no room below
            cx = (x0 + x1) / 2
            left = int(min(max(wx0 + 4 - sh, cx - W_ / 2), wx1 - 4 + sh - W_))
            img, sh, cy0, chh, ah = self._render(text, s, below, cx - left)
            top = int(y1 + gap - sh) if below else int(y0 - gap - (H_ - sh))
            top = max(wy0 - sh, min(top, wy1 + sh - H_))
            self.img = img; self.final = (left, top); dy = int(2 * s) * (1 if below else -1)
            try:                                                    # owned by the anchor's window (not globally topmost); set while hidden
                own = _w.winfo_toplevel() if _w is not None else self.root
                if str(self.w.transient() or "") != str(own): self.w.transient(own)
            except Exception: pass
            if self.layered:
                self.w.geometry("%dx%d+%d+%d" % (W_, H_, left, top)); self._ensure_layered()
                self.pos = (left, top + (dy if slide else 0)); self._push(0.0 if slide else 1.0)   # content first, then map: never an empty box
            else: self._tkimg = ImageTk.PhotoImage(img); self.label.config(image=self._tkimg); self.w.attributes("-alpha", 0.0)
            self.w.deiconify(); self.shown = True
            try: self.w.lift()
            except Exception: pass
            if not slide: self.pos = (left, top); self._push(1.0); return
            t0 = time.time()
            def step():
                k = min(1.0, (time.time() - t0) * 1000 / self.FIN); e = 1 - (1 - k) ** 3
                self.pos = (left, int(top + dy * (1 - e))); self._push(e)
                self.anim = self.root.after(15, step) if k < 1 else None
            step()
        except Exception as ex: log("Tooltip: %r" % ex)
    def hide(self, _=None, fade=True):
        self._cancel(); self.key = None; self.want = None
        if self.wd:
            try: self.root.after_cancel(self.wd)
            except Exception: pass
            self.wd = None
        if not self.shown:
            if self._visible(): self._gone()
            return
        self.shown = False; self.t_hide = time.time()
        try:
            if not fade or not self.img: self._gone(); return
            t0 = time.time()
            def step():
                self.anim = None
                if self.shown: return                             # re-shown meanwhile
                try:
                    k = min(1.0, (time.time() - t0) * 1000 / self.FOUT)
                    if k >= 1: self._gone(); return
                    self._push(1 - k); self.anim = self.root.after(15, step)
                except Exception: self._gone()
            step()
        except Exception: self._gone()
def ImageChops_offset(im, dx, dy):
    out = Image.new(im.mode, im.size, 0); out.paste(im, (dx, dy)); return out
def get_tip(widget):
    """The shared tooltip for this widget's Tk root (created on first use). Also hides on minimise/move/focus loss."""
    root = widget._root()
    t = getattr(root, "_glass_tip", None)
    if t is None:
        t = GlassTip(root); root._glass_tip = t
    tl = widget.winfo_toplevel()
    if not getattr(tl, "_tip_hooks", False):
        tl._tip_hooks = True; last = {"geo": None}
        def cfg(e):
            if e.widget is tl:
                g = (tl.winfo_rootx(), tl.winfo_rooty())
                if last["geo"] and g != last["geo"]: t.hide(fade=False)
                last["geo"] = g
        tl.bind("<Configure>", cfg, add="+"); tl.bind("<Unmap>", lambda e: t.hide(fade=False), add="+")
        tl.bind("<FocusOut>", lambda e: tl.after(60, lambda: (tl.focus_displayof() is None) and not t._ours_fg() and t.hide()), add="+")
        tl.bind("<Destroy>", lambda e: e.widget is tl and t.hide(fade=False), add="+")
    return t
def canvas_rect(cv, bbox):
    """Canvas bbox (px) -> screen rect."""
    x0, y0, x1, y1 = bbox; rx, ry = cv.winfo_rootx(), cv.winfo_rooty()
    return (rx + x0, ry + y0, rx + x1, ry + y1)
def after_mouse_up(w, cb, min_ms=150):
    """Call cb once the left mouse button is released (anywhere, even outside the app) and min_ms passed."""
    t0 = time.time()
    def down():
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception: return False
    def poll():
        try:
            if down() or (time.time() - t0) * 1000 < min_ms: w.after(30, poll)
            else: cb()
        except Exception: pass                       # window closed meanwhile
    poll()
class _Pen:
    """Icon drawing in a 22-unit space around the centre (supersampled by the caller)."""
    def __init__(s_, d, m): s_.d = d; s_.k = m / 22.0; s_.c = m / 2.0
    def p(s_, x, y): return (s_.c + x * s_.k, s_.c + y * s_.k)
    def rr(s_, x0, y0, x1, y1, r, fill=None, outline=None, w=1.6):
        s_.d.rounded_rectangle([*s_.p(x0, y0), *s_.p(x1, y1)], radius=r * s_.k, fill=fill, outline=outline, width=max(1, int(w * s_.k)) if outline else 0)
    def circ(s_, x, y, r, fill=None, outline=None, w=1.6):
        s_.d.ellipse([*s_.p(x - r, y - r), *s_.p(x + r, y + r)], fill=fill, outline=outline, width=max(1, int(w * s_.k)) if outline else 0)
    def poly(s_, pts, fill): s_.d.polygon([s_.p(x, y) for x, y in pts], fill=fill)
    def line(s_, pts, col, w):
        P_ = [s_.p(x, y) for x, y in pts]; s_.d.line(P_, fill=col, width=max(1, int(w * s_.k)), joint="curve"); r = w * s_.k / 2
        for x, y in P_: s_.d.ellipse([x - r, y - r, x + r, y + r], fill=col)
def _pen_icon(name, col, bg):
    def paint(v):
        if name == "link":
            v.rr(-9, -4, 1, 4, 4, outline=col, w=1.8); v.rr(-1, -4, 9, 4, 4, outline=col, w=1.8)
        elif name == "plus": v.line([(-5, 0), (5, 0)], col, 2); v.line([(0, -5), (0, 5)], col, 2)
        elif name == "drop":                                   # arrow down into a tray
            v.line([(0, -8), (0, 2)], col, 1.9); v.line([(-4, -2), (0, 2), (4, -2)], col, 1.9)
            v.line([(-8, 2), (-8, 7), (8, 7), (8, 2)], col, 1.9)
        elif name == "search": v.circ(-2, -2, 5.2, outline=col, w=1.9); v.line([(2, 2), (6.5, 6.5)], col, 2.1)
        elif name == "playing":
            for i, h in enumerate((7, 11, 5)): v.rr(-6.5 + i * 4.6, 5.5 - h, -4.1 + i * 4.6, 5.5, 1.1, fill=col)
        elif name == "paste": v.rr(-6, -6, 6, 8, 2, outline=col, w=1.7); v.rr(-3, -8.5, 3, -4.5, 1.5, fill=col)
        elif name == "handle":
            for yy in (-4, 0, 4):
                for xx in (-2.2, 2.2): v.circ(xx, yy, 1.3, fill=col)
        elif name == "x": v.line([(-3.6, -3.6), (3.6, 3.6)], col, 1.7); v.line([(3.6, -3.6), (-3.6, 3.6)], col, 1.7)
        elif name == "back": v.line([(5, 0), (-5, 0)], col, 2); v.line([(-1, -4.5), (-5.5, 0), (-1, 4.5)], col, 2)
        elif name == "note":
            v.circ(-3, 5, 3, fill=col); v.line([(0, 5), (0, -6), (5, -7.5)], col, 1.9)
    return paint
def _dashed_rr(dr, w, h, r, col, lw, dash, gap):
    import math
    pts = []
    def arc(cx, cy, a0, a1):
        for i in range(13):
            a = math.radians(a0 + (a1 - a0) * i / 12.0); pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    x0, y0, x1, y1 = lw, lw, w - lw, h - lw
    arc(x0 + r, y0 + r, 180, 270); arc(x1 - r, y0 + r, 270, 360); arc(x1 - r, y1 - r, 0, 90); arc(x0 + r, y1 - r, 90, 180); pts.append(pts[0])
    on, left = True, dash
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay); t = 0.0
        while L - t > 1e-6:
            stp = min(left, L - t)
            if on: dr.line([(ax + (bx - ax) * t / L, ay + (by - ay) * t / L), (ax + (bx - ax) * (t + stp) / L, ay + (by - ay) * (t + stp) / L)], fill=col, width=max(1, int(lw)))
            t += stp; left -= stp
            if left <= 1e-6: on = not on; left = dash if on else gap
def mosaic_image(tracks, px):
    """2x2 mosaic of the first songs' cached album art (1 song: full art), PIL RGB."""
    from PIL import Image
    im = Image.new("RGB", (px, px), "#2a2a2a")
    tr = [t for t in tracks if os.path.exists(track_cover(t))]
    if len(tr) == 1:
        try: return Image.open(track_cover(tr[0])).convert("RGB").resize((px, px), Image.LANCZOS)
        except Exception: return im
    h = px // 2
    for i, t in enumerate((tr * 4)[:4] if tr else []):
        try: im.paste(Image.open(track_cover(t)).convert("RGB").resize((h, h), Image.LANCZOS), ((i % 2) * h, (i // 2) * h))
        except Exception: pass
    return im
def save_mosaic(uri, tracks, px=96):
    try:
        os.makedirs(COVERS, exist_ok=True); mosaic_image(tracks, px).save(custom_cover(uri)); return custom_cover(uri)
    except Exception as e: log("Mosaic cover: %r" % e); return None
def install_edit_menu(w):
    """Right-click Cut / Copy / Paste / Select all for every Entry and Text in this Tk app."""
    import tkinter as tk
    m = tk.Menu(w, tearoff=0, bg="#2a2a2a", fg="#f2f2f2", activebackground="#1DB954", activeforeground="#121212",
                bd=0, relief="flat", font=("Segoe UI", 10))
    tgt = {}
    def do(ev):
        x = tgt.get("w")
        if x is not None:
            try: x.focus_set(); x.event_generate(ev)
            except tk.TclError: pass
    def sel_all():
        x = tgt.get("w")
        if x is None: return
        try: x.focus_set(); x.select_range(0, "end"); x.icursor("end")
        except Exception:
            try: x.tag_add("sel", "1.0", "end")
            except Exception: pass
    m.add_command(label="Cut", command=lambda: do("<<Cut>>")); m.add_command(label="Copy", command=lambda: do("<<Copy>>"))
    m.add_command(label="Paste", command=lambda: do("<<Paste>>")); m.add_separator(); m.add_command(label="Select all", command=sel_all)
    def show(e):
        tgt["w"] = e.widget
        try: m.tk_popup(e.x_root, e.y_root)
        finally:
            try: m.grab_release()
            except tk.TclError: pass
    for cls in ("Entry", "Text"): w.bind_class(cls, "<Button-3>", show, add="+")
