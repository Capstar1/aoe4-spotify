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
}
