# marbec-gpu et marbec-data

Estimation de l'empreinte carbone des serveurs du DEN hébergés au CINES (marbec-gpu et marbec-data).

Les deux serveurs sont allumés en continu, consommation sur l'année :

- énergie (kWh) = puissance (W) x heures / 1000 x PUE
- émissions (kgCO2e) = énergie x facteur d'émission de l'électricité

## Fichiers

- `extraire_donnees_marbec_gpu.sh` : export des jobs SLURM (`sacct`), description du matériel et lecture `ipmitool`. A lancer sur marbec-gpu avec `sudo`.
- `suivi_puissance.sh` : relevé toutes les 5 minutes de la puissance du serveur (`ipmitool`) et des GPU (`nvidia-smi`), dans `/var/log/bilan-carbone/`.
- `bilan_carbone_marbec_gpu_anonime.ipynb` : calcul du bilan, répartition indicative par utilisateur, statistiques d'utilisation et section marbec-data.
- `data/` : données anonymisées (logins remplacés par `user01`, `user02`...).


PUE du CINES : 1,22 (rapport d'activité 2025). Facteur électricité : 0,0519 kgCO2e/kWh (ADEME, mix 2024).
