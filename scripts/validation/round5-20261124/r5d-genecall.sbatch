#!/bin/bash
#SBATCH --job-name=r5d-genecall
#SBATCH --account=k10018
#SBATCH --partition=workq
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/scratch/project/k10018/work/eq-round5-20261124/data/genecall/%x-%j.log
set -euo pipefail
W=/scratch/project/k10018/work/eq-round5-20261124/data/genecall
/project/k10018/sw/envs/gspa-tools/bin/python $W/genecall_compare.py $W/out ${LIMIT:-0}
