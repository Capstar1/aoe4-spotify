//! Game-independent core: events, log tail, switcher, settings. Game specifics live in adapters (aoe4.rs).
pub mod aoe4;
pub mod game;
pub mod logtail;
pub mod settings;
pub mod spotify;
pub mod switcher;
pub mod intros;
pub mod aftermatch;
