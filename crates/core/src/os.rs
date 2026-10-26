//! Small OS helpers shared by every front end. Windows: the 1.0.9 way (rundll32, no console window).
/// Open a URL, file or `spotify:` URI with its default handler.
/// AOE4S_DRYOPEN=<file>: append the target (query string dropped: login URLs carry PKCE state) instead of opening it (tests).
pub fn open(p: &str) -> std::io::Result<()> {
    if let Some(f) = std::env::var_os("AOE4S_DRYOPEN") {
        use std::io::Write; let mut h = std::fs::OpenOptions::new().create(true).append(true).open(f)?;
        return writeln!(h, "{}", p.split('?').next().unwrap_or(p));
    }
    open_os(p)
}
#[cfg(windows)]
fn open_os(p: &str) -> std::io::Result<()> {
    use std::os::windows::process::CommandExt;
    std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", p]).creation_flags(0x0800_0000).spawn().map(|_| ())
}
#[cfg(not(windows))]
fn open_os(p: &str) -> std::io::Result<()> { std::process::Command::new("xdg-open").arg(p).spawn().map(|_| ()) }

/// The user's real Documents folder (moved/OneDrive-aware); falls back to %USERPROFILE%\Documents.
pub fn documents_dir() -> Option<std::path::PathBuf> {
    known_documents().or_else(|| std::env::var_os("USERPROFILE").map(|h| std::path::PathBuf::from(h).join("Documents")))
}
#[cfg(windows)]
fn known_documents() -> Option<std::path::PathBuf> {
    use std::os::windows::ffi::OsStringExt;
    #[repr(C)] struct Guid(u32, u16, u16, [u8; 8]);
    const FOLDERID_DOCUMENTS: Guid = Guid(0xFDD39AD0, 0x238F, 0x46AF, [0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7]);
    #[link(name = "shell32")] extern "system" { fn SHGetKnownFolderPath(id: *const Guid, flags: u32, tok: isize, out: *mut *mut u16) -> i32; }
    #[link(name = "ole32")] extern "system" { fn CoTaskMemFree(p: *mut std::ffi::c_void); }
    unsafe {
        let mut p: *mut u16 = std::ptr::null_mut();
        let hr = SHGetKnownFolderPath(&FOLDERID_DOCUMENTS, 0, 0, &mut p);
        let r = (hr == 0 && !p.is_null()).then(|| { let n = (0..).take_while(|&i| *p.add(i) != 0).count(); std::ffi::OsString::from_wide(std::slice::from_raw_parts(p, n)).into() });
        CoTaskMemFree(p.cast());
        r.filter(|d: &std::path::PathBuf| !d.as_os_str().is_empty())
    }
}
#[cfg(not(windows))]
fn known_documents() -> Option<std::path::PathBuf> { None }

#[cfg(test)]
mod tests {
    #[test]
    fn dry_open_logs_without_query() {
        let f = std::env::temp_dir().join(format!("dryopen_{}.txt", std::process::id())); let _ = std::fs::remove_file(&f);
        std::env::set_var("AOE4S_DRYOPEN", &f);
        super::open("https://accounts.spotify.com/authorize?client_id=x&code_challenge=y").unwrap();
        std::env::remove_var("AOE4S_DRYOPEN");
        assert_eq!(std::fs::read_to_string(&f).unwrap(), "https://accounts.spotify.com/authorize\n"); let _ = std::fs::remove_file(&f);
    }
    #[test]
    fn documents_dir_is_absolute() {
        if let Some(d) = super::documents_dir() { assert!(d.is_absolute(), "{d:?}"); }
        #[cfg(windows)] assert!(super::known_documents().is_some());
    }
}
