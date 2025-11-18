use std::path::PathBuf;

use clap::Args;

#[derive(Debug, Args)]
pub struct RepoArgs {
    #[arg(long, default_value = ".")]
    pub repo: PathBuf,
}

impl RepoArgs {
    pub fn repo_root(&self) -> PathBuf {
        self.repo.canonicalize().unwrap_or_else(|_| self.repo.clone())
    }
}
