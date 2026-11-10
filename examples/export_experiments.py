"""Regenerate the protocol-v0 research ledger, preserving human observations."""
import argparse
from pathlib import Path

from evaluation.research_workbook import export
from wt.paths import REPO_ROOT


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiments', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=REPO_ROOT / '.runtime/experiments-protocolv0-regenerated.xlsx')
    parser.add_argument('--audit', type=Path, help='Optional JSON audit with source hashes and cell provenance')
    args = parser.parse_args()
    print(export(args.experiments, args.out, audit_path=args.audit))
