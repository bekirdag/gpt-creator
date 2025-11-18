use crate::index::{DocSnapshot, Hit, Indexer, SnippetOrigin};
use anyhow::Result;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Json},
    routing::get,
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::warn;

const DEFAULT_SNIPPET_WINDOW: usize = 60;
const MIN_SNIPPET_WINDOW: usize = 10;
const MAX_SNIPPET_WINDOW: usize = 400;

#[derive(Clone)]
pub struct AppState(pub Arc<Indexer>);

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/search", get(search_handler))
        .route("/snippet/:doc_id", get(snippet_handler))
        .with_state(state)
}

async fn healthz() -> &'static str {
    "ok"
}

#[derive(Deserialize)]
struct SearchParams {
    q: String,
    limit: Option<usize>,
}

#[derive(Serialize)]
struct SearchResponse {
    hits: Vec<Hit>,
}

pub async fn run_query(indexer: &Indexer, query: &str, limit: usize) -> Result<SearchResponse> {
    let hits = indexer.search(query, limit)?;
    Ok(SearchResponse { hits })
}

async fn search_handler(
    State(state): State<AppState>,
    Query(params): Query<SearchParams>,
) -> impl IntoResponse {
    let limit = params.limit.unwrap_or(8);
    match state.0.search(&params.q, limit) {
        Ok(hits) => Json(SearchResponse { hits }).into_response(),
        Err(err) => {
            warn!(
                target: "docdexd",
                error = ?err,
                query = %params.q,
                limit,
                "search handler failed"
            );
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                err.to_string(),
            )
                .into_response()
        }
    }
}

#[derive(Deserialize)]
struct SnippetParams {
    window: Option<usize>,
    q: Option<String>,
}

#[derive(Serialize)]
struct SnippetPayload {
    text: String,
    html: Option<String>,
    truncated: bool,
    origin: SnippetOrigin,
}

#[derive(Serialize)]
struct SnippetResponse {
    doc: Option<DocSnapshot>,
    snippet: Option<SnippetPayload>,
}

async fn snippet_handler(
    State(state): State<AppState>,
    Path(doc_id): Path<String>,
    Query(params): Query<SnippetParams>,
) -> impl IntoResponse {
    let window = params
        .window
        .unwrap_or(DEFAULT_SNIPPET_WINDOW)
        .clamp(MIN_SNIPPET_WINDOW, MAX_SNIPPET_WINDOW);
    match state
        .0
        .snapshot_with_snippet(&doc_id, params.q.as_deref(), window)
    {
        Ok(Some((doc, snippet))) => {
            let payload = snippet.map(|snippet| SnippetPayload {
                text: snippet.text,
                html: snippet.html,
                truncated: snippet.truncated,
                origin: snippet.origin,
            });
            Json(SnippetResponse {
                doc: Some(doc),
                snippet: payload,
            })
            .into_response()
        }
        Ok(None) => Json(SnippetResponse { doc: None, snippet: None }).into_response(),
        Err(err) => {
            warn!(
                target: "docdexd",
                error = ?err,
                doc_id = %doc_id,
                window,
                "snippet handler failed"
            );
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                err.to_string(),
            )
                .into_response()
        }
    }
}
