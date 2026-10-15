//! Follows a growing text log: new complete lines since the last poll; survives truncation / recreation.
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;

pub struct Tail {
    pub path: PathBuf,
    pos: u64,
    partial: String,
}

pub enum Poll {
    Lines(Vec<String>),
    /// File shrank or was recreated: caller resets the adapter's session state.
    Restarted(Vec<String>),
    Missing,
}

impl Tail {
    pub fn new(path: PathBuf) -> Self { Tail { path, pos: 0, partial: String::new() } }

    /// Jump to the current end and drop a partial line. False when the file is not there yet.
    pub fn skip_to_end(&mut self) -> bool {
        let Ok(f) = File::open(&self.path) else { return false };
        self.pos = f.metadata().map(|m| m.len()).unwrap_or(0);
        self.partial.clear();
        true
    }

    pub fn poll(&mut self) -> Poll {
        let mut f = match File::open(&self.path) { Ok(f) => f, Err(_) => return Poll::Missing };
        let len = f.metadata().map(|m| m.len()).unwrap_or(0);
        let restarted = len < self.pos;
        if restarted { self.pos = 0; self.partial.clear(); }
        if len == self.pos { return Poll::Lines(vec![]); }
        if f.seek(SeekFrom::Start(self.pos)).is_err() { return Poll::Lines(vec![]); }
        let mut buf = Vec::with_capacity((len - self.pos) as usize);
        let _ = (&mut f).take(len - self.pos).read_to_end(&mut buf);
        self.pos += buf.len() as u64;
        self.partial.push_str(&String::from_utf8_lossy(&buf));
        let mut lines = vec![];
        while let Some(i) = self.partial.find('\n') {
            let l: String = self.partial.drain(..=i).collect();
            lines.push(l.trim_end_matches(['\r', '\n']).to_string());
        }
        if restarted { Poll::Restarted(lines) } else { Poll::Lines(lines) }
    }
}

#[cfg(test)]
mod skip_tests {
    use super::*;
    #[test]
    fn skip_to_end_ignores_what_is_already_there() {
        let p = std::env::temp_dir().join(format!("aoe4s_tail_{}", std::process::id()));
        std::fs::write(&p, "old\n").unwrap();
        let mut t = Tail::new(p.clone());
        assert!(t.skip_to_end());
        assert!(matches!(t.poll(), Poll::Lines(ref v) if v.is_empty()));
        let mut f = std::fs::OpenOptions::new().append(true).open(&p).unwrap();
        use std::io::Write;
        writeln!(f, "new").unwrap();
        match t.poll() { Poll::Lines(v) => assert_eq!(v, vec!["new".to_string()]), Poll::Restarted(v) => panic!("restarted {v:?}"), Poll::Missing => panic!("missing") }
        let _ = std::fs::remove_file(&p);
    }
}