#!/usr/bin/env bash
#relevé toutes les 5 minutes

# /var/log/bilan-carbone/gpu_power.csv
# /var/log/bilan-carbone/gpu_jobs.csv
# /var/log/bilan-carbone/serveur_power.csv

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
umask 022
DIR=/var/log/bilan-carbone
mkdir -p "$DIR"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,power.draw,utilization.gpu,memory.used \
             --format=csv,noheader,nounits 2>/dev/null \
  | sed "s/^/${TS},/" | tr -d ' ' >> "$DIR/gpu_power.csv"

  # qui utilise chaque GPU
  CARTES=$(nvidia-smi --query-gpu=index,uuid --format=csv,noheader 2>/dev/null | tr -d ' ')

  nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null \
  | tr -d ' ' | while IFS=, read -r uuid pid mem; do
      [ -z "$pid" ] && continue
      gpu=$(echo "$CARTES" | awk -F, -v u="$uuid" '$2 == u {print $1}')
      job=$(grep -o 'job_[0-9]*' "/proc/$pid/cgroup" 2>/dev/null | head -1 | cut -d_ -f2)
      if [ -z "$job" ]; then
        user=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
        job="hors_slurm:${user:-inconnu}"
      fi
      echo "${TS},${gpu},${job},${mem}"
    done >> "$DIR/gpu_jobs.csv"
fi

if command -v ipmitool >/dev/null 2>&1; then
  W=$(ipmitool dcmi power reading 2>/dev/null \
      | awk -F: '/power/ {gsub(/[^0-9]/,"",$2); print $2}')
  [ -n "$W" ] && echo "${TS},${W}" >> "$DIR/serveur_power.csv"
fi
