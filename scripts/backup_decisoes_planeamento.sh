#!/usr/bin/env bash
# Cópia diária das decisões do planeamento: esquema planning_mtg da base dataresearchmtg.
# Ficam de fora só os DADOS das duas caches reconstruíveis a partir do Excel
# (raw_contents, ~16 GB, e raw_members, ~1 GB); a estrutura dessas tabelas é copiada.
# Só lê a base (pg_dump). Guarda em $PLANNING_BACKUP_DIR (por omissão ~/backups/planeamento),
# ficheiros legíveis só pelo dono, e apaga cópias com mais de $PLANNING_BACKUP_KEEP_DAYS dias.
set -euo pipefail

DEST="${PLANNING_BACKUP_DIR:-$HOME/backups/planeamento}"
KEEP_DAYS="${PLANNING_BACKUP_KEEP_DAYS:-30}"
CONTAINER="${PLANNING_PG_CONTAINER:-postgres}"
DB="${PLANNING_PG_DB:-dataresearchmtg}"

umask 077
mkdir -p "$DEST"
stamp="$(date +%Y%m%d-%H%M%S)"
part="$DEST/.planning_mtg-$stamp.dump.part"
out="$DEST/planning_mtg-$stamp.dump"
trap 'rm -f "$part"' EXIT

docker exec "$CONTAINER" pg_dump -U postgres -d "$DB" -n planning_mtg \
    --exclude-table-data=planning_mtg.raw_contents \
    --exclude-table-data=planning_mtg.raw_members \
    -Fc > "$part"

# Confirma que o ficheiro é um arquivo pg_dump legível antes de o dar como bom.
docker exec -i "$CONTAINER" pg_restore --list < "$part" > /dev/null

mv "$part" "$out"
trap - EXIT
find "$DEST" -maxdepth 1 -name 'planning_mtg-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "cópia criada: $out ($(du -h "$out" | cut -f1))"
