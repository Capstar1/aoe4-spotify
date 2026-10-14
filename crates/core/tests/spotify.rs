use aoe4core::spotify::{challenge, enc};
#[test] fn pkce_challenge_matches_sha256_b64url() { assert_eq!(challenge("dBjftJeZ4CVP-mJ92K9qMxUcmUPJ6h66ZR0uO0m3qf4"), "Ti38Hx4dGWwRjQY1bcQxdn5GFgTdVtPdPRGb-oH7MD4"); }
#[test] fn url_encoding() { assert_eq!(enc("http://127.0.0.1:8888/callback"), "http%3A%2F%2F127.0.0.1%3A8888%2Fcallback"); assert_eq!(enc("a b"), "a%20b"); }
