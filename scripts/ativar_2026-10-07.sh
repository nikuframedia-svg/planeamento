#!/usr/bin/env bash
# Ativação de 07/10/2026: mínimo de burocracia (ramo release-20261007).
# Passos: confirmar → parar os 3 serviços → trazer o código → repor os hard links com o MES → arrancar → conferir.
# Retorno e pormenores: docs/plano-carteira-perfis-2026-10-02/EXECUCAO.md, secção 07/10/2026.
set -euo pipefail

REPO=/home/luis/projects/planeamento
MES=/home/luis/projects/kanban-mes-mtg2
BASE=c074a8f
RELEASE=release-20261007
LINKED=(app/web/static/need_editor.js app/web/static/need_editor.css app/web/static/capacity.js)
BASE_URL=http://127.0.0.1:8113

cd "$REPO"

echo "1/6 Confirmar o ponto de partida"
git merge-base --is-ancestor HEAD "$RELEASE" || { echo "O ramo atual não é antecessor de $RELEASE. Pára."; exit 1; }
[ "$(git rev-parse --short=7 HEAD)" = "$BASE" ] || echo "Aviso: HEAD não é $BASE (é $(git rev-parse --short=7 HEAD))."
.venv/bin/python - <<'PY'
import scripts.audit_readonly as a
with a.planning_db() as c:
    busy = a.query(c, "SELECT count(*) n FROM planning_mtg.raw_jobs WHERE status IN ('queued','running')")[0]["n"]
print(f"   cálculos em fila ou a correr: {busy}")
if busy:
    raise SystemExit("   Há cálculos a correr. Espera que acabem e volta a correr o script.")
PY
df -h / | tail -1 | awk '{print "   disco livre: "$4" ("$5" ocupado)"}'

echo "2/6 Parar kanban-planning, kanban-raw-worker e kanban-research-sync"
systemctl --user stop kanban-planning kanban-raw-worker kanban-research-sync

echo "3/6 Trazer o código ($RELEASE, só avanço rápido)"
git merge --ff-only "$RELEASE"

echo "4/6 Repor os hard links com o MES (o mesmo ficheiro físico nas duas apps)"
for f in "${LINKED[@]}"; do
    cat "$REPO/$f" > "$MES/$f"        # conteúdo novo no ficheiro do MES (mesmo inode)
    ln -f "$MES/$f" "$REPO/$f"         # o planeamento passa a apontar para esse ficheiro (conteúdo igual)
    read -r links_r inode_r < <(stat -c '%h %i' "$REPO/$f")
    read -r links_m inode_m < <(stat -c '%h %i' "$MES/$f")
    [ "$inode_r" = "$inode_m" ] && [ "$links_r" = 2 ] || { echo "   Hard link falhou em $f"; exit 1; }
    echo "   $f: inode $inode_r, 2 ligações"
done
git diff --quiet HEAD -- "${LINKED[@]}" || { echo "   Os ficheiros ligados diferem do commit. Pára."; exit 1; }

echo "5/6 Arrancar"
systemctl --user start kanban-planning
for i in $(seq 1 60); do
    curl -fsS -o /dev/null "$BASE_URL/planeamento/manual" 2>/dev/null && break
    sleep 1
done
for page in /planeamento/manual /planeamento/carteira /planeamento/setor/carga /planeamento/gantt; do
    printf '   %-28s %s\n' "$page" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL$page")"
done
systemctl --user start kanban-raw-worker kanban-research-sync
systemctl --user is-active kanban-planning kanban-raw-worker kanban-research-sync kanban-planning-tunnel

echo "6/6 Conferir (o recálculo completo demora 2–3 min; as gravações esperam por ele)"
echo "   journalctl --user -u kanban-planning -u kanban-raw-worker -f   (procurar Traceback, ImportError, ValueError)"
echo "   Pedir para recarregar os separadores abertos (Registar, Tabela, Carteira, Gantt)."
