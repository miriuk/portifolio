"""Entrypoint for Streamlit Community Cloud / Hugging Face Spaces.

Locally, `cryptoarena dashboard` does the same thing with the package
installed; here we add `src/` to the path so a bare checkout works too.
"""
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

# Hosted deploys keep secrets in Streamlit's store, the code reads env vars.
# `st.secrets` raises (not just returns empty) when no secrets.toml exists.
try:
    secrets = dict(st.secrets)
except Exception:
    secrets = {}
for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CRYPTOARENA_DB_URL"):
    if key in secrets and key not in os.environ:
        os.environ[key] = str(secrets[key])

from cryptoarena.dashboard import main  # noqa: E402

main()
