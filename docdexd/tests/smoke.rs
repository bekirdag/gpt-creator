use assert_cmd::prelude::*;
use reqwest::blocking::Client;
use serde_json::Value;
use std::error::Error;
use std::ffi::OsStr;
use std::fs;
use std::net::TcpListener;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};
use tempfile::TempDir;

fn write_fixture_repo(repo_root: &Path) -> Result<(), Box<dyn Error>> {
    let docs_dir = repo_root.join("docs");
    fs::create_dir_all(&docs_dir)?;
    fs::write(
        docs_dir.join("overview.md"),
        r#"
# Platform Overview

Our roadmap includes authentication, billing, and observability upgrades.

## Authentication

Detailed description about the auth roadmap.
        "#,
    )?;
    fs::write(
        repo_root.join("readme.md"),
        r#"
# Internal README

This repository hosts design docs for the Control Plane roadmap.
        "#,
    )?;
    Ok(())
}

fn setup_repo() -> Result<TempDir, Box<dyn Error>> {
    let temp = TempDir::new()?;
    write_fixture_repo(temp.path())?;
    Ok(temp)
}

fn run_docdex<I, S>(args: I) -> Result<Vec<u8>, Box<dyn Error>>
where
    I: IntoIterator<Item = S>,
    S: AsRef<std::ffi::OsStr>,
{
    let output = Command::cargo_bin("docdexd")?.args(args).output()?;
    if !output.status.success() {
        return Err(format!(
            "docdexd exited with {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        )
        .into());
    }
    Ok(output.stdout)
}

fn pick_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("bind ephemeral port")
        .local_addr()
        .unwrap()
        .port()
}

fn wait_for_health(host: &str, port: u16) -> Result<(), Box<dyn Error>> {
    let client = Client::builder().timeout(Duration::from_secs(1)).build()?;
    let url = format!("http://{host}:{port}/healthz");
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        match client.get(&url).send() {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            _ => thread::sleep(Duration::from_millis(200)),
        }
    }
    Err("docdexd healthz endpoint did not respond in time".into())
}

#[test]
fn cli_index_and_query_smoke() -> Result<(), Box<dyn Error>> {
    let repo = setup_repo()?;
    let repo_str = repo.path().to_string_lossy().to_string();

    run_docdex(["index", "--repo", repo_str.as_str()])?;

    let stdout = run_docdex([
        "query",
        "--repo",
        repo_str.as_str(),
        "--query",
        "roadmap",
        "--limit",
        "4",
    ])?;
    let payload: Value = serde_json::from_slice(&stdout)?;
    let hits = payload
        .get("hits")
        .and_then(|value| value.as_array())
        .expect("hits array missing");
    assert!(
        !hits.is_empty(),
        "expected at least one search hit for 'roadmap'"
    );
    let first = hits.first().expect("hit missing");
    let summary = first
        .get("summary")
        .and_then(|value| value.as_str())
        .unwrap_or_default();
    assert!(
        !summary.is_empty(),
        "summary should not be empty in CLI query response"
    );
    Ok(())
}

fn spawn_server(repo_root: &Path, host: &str, port: u16) -> Result<Child, Box<dyn Error>> {
    let repo_arg = repo_root.to_string_lossy().to_string();
    let mut child = Command::cargo_bin("docdexd")?
        .args([
            "serve",
            "--repo",
            repo_arg.as_str(),
            "--host",
            host,
            "--port",
            &port.to_string(),
            "--log",
            "warn",
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    wait_for_health(host, port)?;
    Ok(child)
}

#[test]
fn http_server_smoke() -> Result<(), Box<dyn Error>> {
    let repo = setup_repo()?;
    let repo_str = repo.path().to_string_lossy().to_string();
    run_docdex(["index", "--repo", repo_str.as_str()])?;

    let port = pick_free_port();
    let host = "127.0.0.1";
    let mut child = spawn_server(repo.path(), host, port)?;
    let client = Client::builder().timeout(Duration::from_secs(2)).build()?;
    let url = format!("http://{host}:{port}/search");
    let payload: Value = client
        .get(&url)
        .query(&[("q", "roadmap"), ("limit", "2")])
        .send()?
        .json()?;
    let hit_count = payload
        .get("hits")
        .and_then(|value| value.as_array())
        .map(|arr| arr.len())
        .unwrap_or(0);
    assert!(hit_count > 0, "HTTP /search should return at least one hit");
    child.kill().ok();
    child.wait().ok();
    Ok(())
}
