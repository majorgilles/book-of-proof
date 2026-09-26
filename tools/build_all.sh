#!/bin/sh
# Full rebuild from work/Main.pdf: convert -> swap checked LaTeX into math crops -> assemble site.
set -e
rm -rf site/figs            # crops are regenerated; never publish stale ones
sh tools/convert_all.sh
python tools/crops.py apply
python tools/build.py
