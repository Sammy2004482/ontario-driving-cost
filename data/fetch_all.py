"""Run every download script in dependency order.  python -m data.fetch_all [--refresh]"""
from data import fetch_boc, fetch_eia, fetch_fremtpl, fetch_nrcan, fetch_statcan

if __name__ == "__main__":
    for mod in (fetch_statcan, fetch_boc, fetch_eia, fetch_nrcan, fetch_fremtpl):
        mod.main()
