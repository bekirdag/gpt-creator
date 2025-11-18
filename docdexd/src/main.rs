mod config;
mod daemon;
mod index;
mod search;
mod util;
mod watcher;

use crate::config::RepoArgs;
use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;
use tracing::info;

#[derive(Parser, Debug)]
#[command(name = "docdexd", version, about = "Documentation index/search daemon")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Serve HTTP API for search/snippets.
    Serve {
        #[command(flatten)]
        repo: RepoArgs,
        #[arg(long, default_value = "127.0.0.1")]
        host: String,
        #[arg(long, default_value_t = 46137)]
        port: u16,
        #[arg(long, default_value = "info")]
        log: String,
    },
    /// Build or rebuild the entire index for a repo.
    Index {
        #[command(flatten)]
        repo: RepoArgs,
    },
    /// Ingest a single document file (incremental update).
    Ingest {
        #[command(flatten)]
        repo: RepoArgs,
        #[arg(long)]
        file: PathBuf,
    },
    /// Run an ad-hoc query via CLI (JSON output).
    Query {
        #[command(flatten)]
        repo: RepoArgs,
        #[arg(short, long)]
        query: String,
        #[arg(long, default_value_t = 8)]
        limit: usize,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Serve {
            repo,
            host,
            port,
            log,
        } => {
            let repo = repo.repo_root();
            util::init_logging(&log)?;
            info!(
                "Starting docdex daemon on {host}:{port} (repo={})",
                repo.display()
            );
            daemon::serve(repo, host, port).await?;
        }
        Command::Index { repo } => {
            let repo = repo.repo_root();
            util::init_logging("info")?;
            info!("Rebuilding index for {}", repo.display());
            index::Indexer::new(repo)?.reindex_all().await?;
        }
        Command::Ingest { repo, file } => {
            let repo = repo.repo_root();
            util::init_logging("warn")?;
            index::Indexer::new(repo)?.ingest_file(file).await?;
        }
        Command::Query { repo, query, limit } => {
            let repo = repo.repo_root();
            util::init_logging("warn")?;
            let server = index::Indexer::new(repo)?;
            let hits = search::run_query(&server, &query, limit).await?;
            println!("{}", serde_json::to_string_pretty(&hits)?);
        }
    }
    Ok(())
}
