//! Windows-only system code (registry, Steam, processes, DWM/layered shadow window). Empty on other targets,
//! so the cross-platform crates and the Slint UI still build and test on Linux.
#![deny(warnings)]
#[cfg(windows)] pub mod launcher;
#[cfg(windows)] pub mod shadow;
