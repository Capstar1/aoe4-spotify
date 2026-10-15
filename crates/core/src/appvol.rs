//! Windows per-app volume of Spotify.exe (1.0.9 `SpotifySession`). Smooth and local: 60 fps, no network.
//! The Web API volume is a fallback for a phone or another PC. A crash mid-fade leaves `fade_restore.json`;
//! the next launch puts the level back only if Spotify is still exactly where we left it.
use serde_json::{json, Value};

/// Quiet point of a switch: about 2% loudness, not silence (1.0.9 `FADE_FLOOR_DB`).
const FLOOR_DB: f32 = -34.0;

/// Amplitude for fade position `t` (0 = full, 1 = floor). Linear in decibels, cosine ease at both ends.
pub fn fade_gain(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    let e = 0.5 - 0.5 * (std::f32::consts::PI * t).cos();
    10f32.powf(FLOOR_DB * e / 20.0)
}

fn sandbox() -> bool {
    std::env::var("AOE4S_TEST").ok().as_deref() == Some("1")
        || std::env::var_os("AOE4S_SHOT").is_some()
        || std::env::var_os("AOE4S_BTRTEST").is_some()
}

fn guard_path() -> std::path::PathBuf { crate::userstore::data_dir().join("fade_restore.json") }

/// While a local fade runs: the level to go back to, and the level we last set. `None` removes the file.
pub fn guard(orig: Option<f32>, last: Option<f32>) {
    let p = guard_path();
    if orig.is_none() { let _ = std::fs::remove_file(&p); return; }
    let _ = std::fs::create_dir_all(crate::userstore::data_dir());
    let body = json!({ "v": orig, "last": last }).to_string();
    let tmp = p.with_extension("tmp");
    if std::fs::write(&tmp, body).is_ok() { let _ = std::fs::rename(&tmp, &p); }
}

pub fn note(m: &str) {
    use std::io::Write;
    let d = crate::userstore::data_dir();
    let _ = std::fs::create_dir_all(&d);
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) + 2 * 3600;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(d.join("aoe4_spotify.log")) {
        let _ = writeln!(f, "{:02}:{:02}:{:02} {m}", (t / 3600) % 24, (t / 60) % 60, t % 60);
    }
}

/// Spotify.exe sessions on the default speakers. Empty when this PC is not what is playing.
pub struct Session {
    #[cfg(windows)]
    vols: Vec<*mut std::ffi::c_void>,
    #[cfg(windows)]
    _com: bool,
}

impl Session {
    pub fn get(&self) -> Option<f32> {
        #[cfg(windows)] { self.vols.first().and_then(|p| unsafe { master_get(*p) }) }
        #[cfg(not(windows))] { None }
    }
    pub fn set(&self, v: f32) -> bool {
        let v = v.clamp(0.0, 1.0);
        #[cfg(windows)] { !self.vols.is_empty() && self.vols.iter().all(|p| unsafe { master_set(*p, v) }) }
        #[cfg(not(windows))] { let _ = v; false }
    }
}

#[cfg(windows)]
impl Drop for Session {
    fn drop(&mut self) {
        for p in self.vols.drain(..) { unsafe { release(p); } }
        if self._com { unsafe { CoUninitialize(); } }
    }
}

pub fn find() -> Option<Session> {
    if sandbox() { return None; }
    #[cfg(windows)] { unsafe { find_sessions() } }
    #[cfg(not(windows))] { None }
}

/// After a crash mid-fade: undo our dip only if Spotify is still at the level we last set.
pub fn restore_after_crash() {
    if sandbox() { return; }
    let p = guard_path();
    let Ok(s) = std::fs::read_to_string(&p) else { return };
    let v: Value = serde_json::from_str(&s).unwrap_or(Value::Null);
    let last = v["last"].as_f64();
    let orig = v["v"].as_f64();
    if let Some(sess) = find() {
        if let (Some(orig), Some(last), Some(cur)) = (orig, last, sess.get()) {
            if (cur as f64 - last).abs() <= 0.01 {
                sess.set(orig as f32);
                note("Restored Spotify app volume after an interrupted fade");
            } else {
                note("Interrupted fade: volume was changed since, leaving it");
            }
        } else {
            note("Interrupted fade: volume was changed since, leaving it");
        }
    }
    let _ = std::fs::remove_file(&p);
}

#[cfg(windows)]
#[link(name = "ole32")]
extern "system" {
    fn CoInitializeEx(r: *mut std::ffi::c_void, flags: u32) -> i32;
    fn CoUninitialize();
    fn CoCreateInstance(clsid: *const Guid, unk: *mut std::ffi::c_void, ctx: u32, iid: *const Guid, out: *mut *mut std::ffi::c_void) -> i32;
}

#[cfg(windows)]
#[repr(C)]
struct Guid { d1: u32, d2: u16, d3: u16, d4: [u8; 8] }
#[cfg(windows)]
fn guid(d1: u32, d2: u16, d3: u16, d4: [u8; 8]) -> Guid { Guid { d1, d2, d3, d4 } }

#[cfg(windows)]
unsafe fn slot(obj: *mut std::ffi::c_void, i: usize) -> *const () {
    let vtbl = *(obj as *const *const *const ());
    *vtbl.add(i)
}
#[cfg(windows)]
unsafe fn release(obj: *mut std::ffi::c_void) {
    let f: unsafe extern "system" fn(*mut std::ffi::c_void) -> u32 = std::mem::transmute(slot(obj, 2));
    f(obj);
}
#[cfg(windows)]
unsafe fn query(obj: *mut std::ffi::c_void, iid: &Guid) -> Option<*mut std::ffi::c_void> {
    let f: unsafe extern "system" fn(*mut std::ffi::c_void, *const Guid, *mut *mut std::ffi::c_void) -> i32 = std::mem::transmute(slot(obj, 0));
    let mut out = std::ptr::null_mut();
    if f(obj, iid, &mut out) >= 0 && !out.is_null() { Some(out) } else { None }
}
#[cfg(windows)]
unsafe fn master_get(obj: *mut std::ffi::c_void) -> Option<f32> {
    let f: unsafe extern "system" fn(*mut std::ffi::c_void, *mut f32) -> i32 = std::mem::transmute(slot(obj, 4));
    let mut v = 0f32;
    (f(obj, &mut v) >= 0).then_some(v)
}
#[cfg(windows)]
unsafe fn master_set(obj: *mut std::ffi::c_void, v: f32) -> bool {
    let f: unsafe extern "system" fn(*mut std::ffi::c_void, f32, *const Guid) -> i32 = std::mem::transmute(slot(obj, 3));
    f(obj, v, std::ptr::null()) >= 0
}

#[cfg(windows)]
fn spotify_pids() -> Vec<u32> {
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> isize;
        fn Process32FirstW(snap: isize, e: *mut ProcessEntry) -> i32;
        fn Process32NextW(snap: isize, e: *mut ProcessEntry) -> i32;
        fn CloseHandle(h: isize) -> i32;
    }
    #[repr(C)]
    struct ProcessEntry {
        size: u32, _cnt: u32, pid: u32, _heap: usize, _mid: u32, _threads: u32, _parent: u32, _pri: i32, _flags: u32,
        exe: [u16; 260],
    }
    unsafe {
        let snap = CreateToolhelp32Snapshot(0x2, 0);
        if snap == 0 || snap == -1 { return vec![]; }
        let mut e: ProcessEntry = std::mem::zeroed();
        e.size = std::mem::size_of::<ProcessEntry>() as u32;
        let mut pids = vec![];
        if Process32FirstW(snap, &mut e) != 0 {
            loop {
                let n = e.exe.iter().position(|&c| c == 0).unwrap_or(e.exe.len());
                if String::from_utf16_lossy(&e.exe[..n]).eq_ignore_ascii_case("spotify.exe") { pids.push(e.pid); }
                if Process32NextW(snap, &mut e) == 0 { break; }
            }
        }
        CloseHandle(snap);
        pids
    }
}

#[cfg(windows)]
unsafe fn find_sessions() -> Option<Session> {
    use std::ffi::c_void;
    let hr = CoInitializeEx(std::ptr::null_mut(), 0);
    let uninit = hr == 0 || hr == 1;
    if !uninit && hr != 0x80010106u32 as i32 { return None; }
    let pids = spotify_pids();
    if pids.is_empty() { if uninit { CoUninitialize(); } return None; }
    let clsid = guid(0xBCDE0395, 0xE52F, 0x467C, [0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E]);
    let enum_iid = guid(0xA95664D2, 0x9614, 0x4F35, [0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6]);
    let mgr_iid = guid(0x77AA99A0, 0x1BD6, 0x484F, [0x8B, 0xC7, 0x2C, 0x65, 0x4C, 0x9A, 0x9B, 0x6F]);
    let ctl2_iid = guid(0xBFB7FF88, 0x7239, 0x4FC9, [0x8F, 0xA2, 0x07, 0xC9, 0x50, 0xBE, 0x9C, 0x6D]);
    let vol_iid = guid(0x87CE5498, 0x68D6, 0x44E5, [0x92, 0x15, 0x6D, 0xA4, 0x7E, 0xF8, 0x83, 0xD8]);
    let fail = |uninit: bool| { if uninit { CoUninitialize(); } None };
    let mut raw = std::ptr::null_mut();
    if CoCreateInstance(&clsid, std::ptr::null_mut(), 23, &enum_iid, &mut raw) < 0 || raw.is_null() { return fail(uninit); }
    let get_ep: unsafe extern "system" fn(*mut c_void, u32, u32, *mut *mut c_void) -> i32 = std::mem::transmute(slot(raw, 4));
    let mut dev = std::ptr::null_mut();
    // eRender = 0, eMultimedia = 1: the default speakers, same as 1.0.9.
    if get_ep(raw, 0, 1, &mut dev) < 0 || dev.is_null() { release(raw); return fail(uninit); }
    release(raw);
    let activate: unsafe extern "system" fn(*mut c_void, *const Guid, u32, *mut c_void, *mut *mut c_void) -> i32 = std::mem::transmute(slot(dev, 3));
    let mut mgr = std::ptr::null_mut();
    if activate(dev, &mgr_iid, 23, std::ptr::null_mut(), &mut mgr) < 0 || mgr.is_null() { release(dev); return fail(uninit); }
    release(dev);
    let get_enum: unsafe extern "system" fn(*mut c_void, *mut *mut c_void) -> i32 = std::mem::transmute(slot(mgr, 5));
    let mut list = std::ptr::null_mut();
    if get_enum(mgr, &mut list) < 0 || list.is_null() { release(mgr); return fail(uninit); }
    release(mgr);
    let get_count: unsafe extern "system" fn(*mut c_void, *mut i32) -> i32 = std::mem::transmute(slot(list, 3));
    let get_sess: unsafe extern "system" fn(*mut c_void, i32, *mut *mut c_void) -> i32 = std::mem::transmute(slot(list, 4));
    let mut n = 0i32;
    if get_count(list, &mut n) < 0 { release(list); return fail(uninit); }
    let mut vols = vec![];
    for i in 0..n {
        let mut ctl = std::ptr::null_mut();
        if get_sess(list, i, &mut ctl) < 0 || ctl.is_null() { continue; }
        let Some(ctl2) = query(ctl, &ctl2_iid) else { release(ctl); continue };
        release(ctl);
        let pid_of: unsafe extern "system" fn(*mut c_void, *mut u32) -> i32 = std::mem::transmute(slot(ctl2, 14));
        let mut pid = 0u32;
        if pid_of(ctl2, &mut pid) < 0 || !pids.contains(&pid) { release(ctl2); continue; }
        match query(ctl2, &vol_iid) { Some(vol) => vols.push(vol), None => {} }
        release(ctl2);
    }
    release(list);
    if vols.is_empty() { return fail(uninit); }
    Some(Session { vols, _com: uninit })
}

#[cfg(test)]
mod tests {
    use super::fade_gain;

    #[test]
    #[cfg(windows)]
    fn a_live_spotify_session_keeps_its_level() {
        let Some(sess) = super::find() else {
            assert!(super::spotify_pids().is_empty(), "Spotify is running but its audio session was not found");
            return;
        };
        let Some(v) = sess.get() else { return };
        assert!(sess.set(v), "could not write the current app volume back");
        let back = sess.get().expect("volume read");
        assert!((back - v).abs() <= 0.02, "read {back} after writing {v}");
    }

    #[test]
    fn fade_gain_starts_full_and_ends_at_the_floor() {
        assert!((fade_gain(0.0) - 1.0).abs() < 1e-5);
        assert!((fade_gain(1.0) - 10f32.powf(-34.0 / 20.0)).abs() < 1e-4);
        let mid = fade_gain(0.5);
        assert!(mid < fade_gain(0.0) && mid > fade_gain(1.0));
        assert!(fade_gain(0.25) > fade_gain(0.75));
    }
}
