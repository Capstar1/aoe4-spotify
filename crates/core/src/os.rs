//! Small OS helpers shared by every front end. Windows: the 1.0.9 way (rundll32, no console window).
/// Open a URL, file or `spotify:` URI with its default handler.
#[cfg(windows)]
pub fn open(p: &str) -> std::io::Result<()> {
    use std::os::windows::process::CommandExt;
    std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", p]).creation_flags(0x0800_0000).spawn().map(|_| ())
}
#[cfg(not(windows))]
pub fn open(p: &str) -> std::io::Result<()> { std::process::Command::new("xdg-open").arg(p).spawn().map(|_| ()) }
