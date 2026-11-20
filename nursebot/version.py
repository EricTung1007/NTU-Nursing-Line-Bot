"""Version string. CI writes nursebot/_version.py from the release tag; source checkouts report a dev version."""
try:
    from ._version import VERSION  # generated at build time, not in git
except ImportError:
    VERSION = "0.0.0-dev"
