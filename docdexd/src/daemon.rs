use crate::index::Indexer;
use crate::search::{self, AppState};
use crate::watcher;
use anyhow::Result;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::{error, info};

pub async fn serve(repo: PathBuf, host: String, port: u16) -> Result<()> {
    let repo_display = repo.display().to_string();
    info!(
        target: "docdexd",
        repo = %repo_display,
        host = %host,
        port,
        "initialising docdex indexer"
    );
    let indexer = Arc::new(Indexer::new(repo)?);
    let state = AppState(indexer.clone());
    watcher::spawn(indexer.repo_root().to_path_buf(), indexer.clone())?;
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    let router = search::router(state);
    info!(
        target: "docdexd",
        repo = %repo_display,
        host = %host,
        port,
        "listening on {addr}"
    );
    let listener = TcpListener::bind(&addr).await?;
    let result = axum::serve(listener, router.into_make_service()).await;
    match result {
        Ok(()) => {
            info!(
                target: "docdexd",
                repo = %repo_display,
                host = %host,
                port,
                "docdex daemon shut down gracefully"
            );
            Ok(())
        }
        Err(err) => {
            error!(
                target: "docdexd",
                repo = %repo_display,
                host = %host,
                port,
                error = ?err,
                "docdex daemon terminated with error"
            );
            Err(err.into())
        }
    }
}
