"""Read the version from installed package data."""
from pkg_resources import get_distribution

__version__ = get_distribution("OpenPGP-Python").version
