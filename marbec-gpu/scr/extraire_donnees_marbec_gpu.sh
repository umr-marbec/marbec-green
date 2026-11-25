#!/usr/bin/env bash
#Bilan carbone marbec-gpu : export des jobs SLURM
#sudo bash extraire_donnees_marbec_gpu.sh 2025                    # une année
#sudo bash extraire_donnees_marbec_gpu.sh 2025-11-26 2026-11-19   # une période

set -euo pipefail

if [[ "${1:-2025}" =~ ^[0-9]{4}$ ]]; then
  DEBUT="${1:-2025}-01-01"; FIN="$(( ${1:-2025} + 1 ))-01-01"; NOM="${1:-2025}"
else
  DEBUT="$1"; FIN="${2:-$(date +%F)}"; NOM="${DEBUT}_${FIN}"
fi
OUT="donnees-marbec-gpu-${NOM}"
mkdir -p "$OUT"

#TotalCPU (CPU real )
sacct -a -S "${DEBUT}T00:00:00" -E "${FIN}T00:00:00" --parsable2 \
  --format=JobID,JobIDRaw,JobName,User,Account,Partition,Start,End,ElapsedRaw,AllocCPUS,AllocTRES,CPUTimeRAW,TotalCPU,State \
  > "$OUT/sacct_${NOM}.csv"
echo "$(awk -F'|' 'NR > 1 && $4 != ""' "$OUT/sacct_${NOM}.csv" | wc -l) jobs du ${DEBUT} au ${FIN}"

{
  echo "### lscpu"; lscpu
  echo; echo "### RAM"; free -g
  echo; echo "### GPU"; nvidia-smi --query-gpu=index,name,power.limit,power.draw,utilization.gpu --format=csv 2>/dev/null || echo "nvidia-smi indisponible"
} > "$OUT/materiel.txt"

ipmitool dcmi power reading > "$OUT/puissance.txt" 2>&1 || echo "ipmitool indisponible" > "$OUT/puissance.txt"

tar czf "${OUT}.tar.gz" "$OUT"
chown -R "${SUDO_USER:-$USER}": "$OUT" "${OUT}.tar.gz"
echo "fichier : ${OUT}.tar.gz"
