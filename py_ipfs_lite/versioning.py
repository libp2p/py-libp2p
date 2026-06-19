import os
import logging

logger = logging.getLogger("py_ipfs_lite.versioning")

REPO_VERSION = "1"

def init_repo_version(repo_path: str) -> None:
    """Initialize or verify the repo version in the given blockstore path."""
    if not os.path.exists(repo_path):
        os.makedirs(repo_path, exist_ok=True)
        
    version_file = os.path.join(repo_path, "version")
    
    if not os.path.exists(version_file):
        with open(version_file, "w") as f:
            f.write(REPO_VERSION)
        logger.info(f"Initialized repo at {repo_path} with version {REPO_VERSION}")
    else:
        with open(version_file, "r") as f:
            current_version = f.read().strip()
            
        if current_version != REPO_VERSION:
            # Here we would normally run migration logic.
            # For now, we simply warn if there is a mismatch.
            logger.warning(
                f"Repo version mismatch! Expected {REPO_VERSION}, found {current_version}. "
                "Migration might be needed in the future."
            )

def get_repo_version(repo_path: str) -> str:
    """Return the current repo version from the version file."""
    version_file = os.path.join(repo_path, "version")
    if os.path.exists(version_file):
        with open(version_file, "r") as f:
            return f.read().strip()
    return "unknown"
