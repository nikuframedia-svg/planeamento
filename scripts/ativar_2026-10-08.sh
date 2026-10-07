#!/usr/bin/env bash
# Ativação de 08/10/2026: Etapa 1 «dados certos» (ramo planeamento-20261008 aqui e no DATARESEARCHMTG).
# Passos: confirmar → parar o timer e os 3 serviços → trazer o código (app e Parte D) → conferir os 17 hard links
# → carregar o Excel do Drive à mão → arrancar o worker e esperar pela geração nova → arrancar o web → conferir.
#
# Diferenças para o de 07/10 (achados P1, P2 e P3 da revisão de 08/10):
# - Não há ficheiros a repor no MES: nenhum dos 17 estáticos em hard link muda. O merge --ff-only só reescreve
#   ficheiros que mudaram, por isso as ligações ficam; o passo 4 confirma-o e pára se não for assim.
# - O planning-research-refresh.timer (às :00, corre app.gantt.research desta pasta, que muda) pára antes e volta
#   no fim.
# - A Parte D (DATARESEARCHMTG: sync_drive.sh lê a raiz e SAIDA/) entra na mesma janela: a app nova procura o
#   Excel nas duas pastas e, sem a Parte D, o Met3 de SAIDA/ ficava «mais recente» para sempre e nunca carregado.
#   Com PARTE_D=0 fica para depois e a app só procura na raiz (drop-in MES_RAW_WORKBOOK_FOLDERS=.).
# - O worker arranca primeiro e o web só quando a geração nova (capacidade v35, planeamento sem agregados
#   pendentes) estiver publicada: as páginas ficam 2–3 min fora do ar, mas não mostram números mistos.
# Horas a evitar (hora do servidor, Berlim): perto das :00 (timer), 08:15 e 14:15 (sync do Drive), 23:30 e 01:30
# (limpeza do disco), 02:25–02:30 (backups). Retorno: git reset --hard 26a37b5 nas duas pastas e voltar a arrancar.
set -euo pipefail

REPO=/home/luis/projects/planeamento
DATA=/home/luis/projects/DATARESEARCHMTG
BASE=26a37b5
RELEASE=${RELEASE:-planeamento-20261008}
DATA_RELEASE=planeamento-20261008  # Parte D
DATA_BASE=930dbd0                 # DATARESEARCHMTG em produção, com a alteração local já gravada em f0d3836
DATA_LOCAL=f0d3836
PARTE_D=${PARTE_D:-1}
LINKED=()                         # 08/10: nada a repor no MES
HARD_LINKS=17                     # estáticos partilhados com o MES (capacity.*, dossiers.*, need_editor.*, …)
CONTRACT=capacity-20260925-integral-v35
WAIT_MINUTES=${WAIT_MINUTES:-15}
SERVICES=(kanban-planning kanban-raw-worker kanban-research-sync)
BASE_URL=http://127.0.0.1:8113

cd "$REPO"

echo "1/8 Confirmar o ponto de partida"
now=$((10#$(date +%H) * 60 + 10#$(date +%M)))
busy=(495 855 1410 90 145 150)    # 08:15, 14:15, 23:30, 01:30, 02:25, 02:30
for hour in $(seq 0 23); do busy+=($((hour * 60))); done   # o timer do Gantt às :00
for at in "${busy[@]}"; do
    d=$(( now > at ? now - at : at - now )); d=$(( d > 720 ? 1440 - d : d ))
    if [ "$d" -le 10 ]; then
        echo "   Agora ($(date +%H:%M)) está a menos de 10 min de uma tarefa agendada. Escolhe outra hora."; exit 1
    fi
done
git merge-base --is-ancestor HEAD "$RELEASE" || { echo "O ramo atual não é antecessor de $RELEASE. Pára."; exit 1; }
[ "$(git rev-parse --short=7 HEAD)" = "$BASE" ] || echo "Aviso: HEAD não é $BASE (é $(git rev-parse --short=7 HEAD))."
[ "$(find app/web/static -links +1 -type f | wc -l)" = "$HARD_LINKS" ] || { echo "   Antes do merge não há $HARD_LINKS estáticos em hard link. Pára."; exit 1; }
if [ "$PARTE_D" = 1 ]; then
    git -C "$DATA" merge-base --is-ancestor HEAD "$DATA_RELEASE" || { echo "   DATARESEARCHMTG: HEAD não é antecessor de $DATA_RELEASE. Pára."; exit 1; }
    [ "$(git -C "$DATA" rev-parse --short=7 HEAD)" = "$DATA_BASE" ] || echo "   Aviso: DATARESEARCHMTG não está em $DATA_BASE."
    git -C "$DATA" diff --quiet "$DATA_LOCAL" -- scripts/sync_drive.sh \
        || { echo "   DATARESEARCHMTG: scripts/sync_drive.sh tem alterações que não estão em $DATA_LOCAL. Pára."; exit 1; }
    pgrep -f "$DATA/scripts/sync_drive.sh" >/dev/null && { echo "   Há um sync_drive.sh a correr. Espera que acabe."; exit 1; }
fi
.venv/bin/python - <<'PY'
import scripts.audit_readonly as a
with a.planning_db() as c:
    busy = a.query(c, "SELECT count(*) n FROM planning_mtg.raw_jobs WHERE status IN ('queued','running')")[0]["n"]
print(f"   cálculos em fila ou a correr: {busy}")
if busy:
    raise SystemExit("   Há cálculos a correr. Espera que acabem e volta a correr o script.")
PY
available=$(awk '/^MemAvailable:/ {print int($2 / 1048576)}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/ {print int($2 / 1048576)}' /proc/meminfo)
swap_total=$(awk '/^SwapTotal:/ {print int($2 / 1048576)}' /proc/meminfo)
echo "   memória disponível: ${available} GB · swap livre: ${swap_free}/${swap_total} GB"
[ "$available" -ge 4 ] || { echo "   Menos de 4 GB de memória disponível: o recálculo completo pode acabar em OOM. Pára."; exit 1; }
[ "$swap_free" -ge 1 ] || echo "   Aviso: swap cheia. Fecha o que não for preciso (ex.: pyrefly no editor) antes de continuar."
df -h / | tail -1 | awk '{print "   disco livre: "$4" ("$5" ocupado)"}'

echo "2/8 Parar o timer do Gantt e os serviços ${SERVICES[*]}"
systemctl --user stop planning-research-refresh.timer
for i in $(seq 1 120); do
    systemctl --user is-active --quiet planning-research-refresh.service || break
    [ "$i" = 1 ] && echo "   À espera que acabe o planning-research-refresh em curso…"
    sleep 5
done
systemctl --user stop "${SERVICES[@]}"

echo "3/8 Trazer o código ($RELEASE, só avanço rápido)"
git merge --ff-only "$RELEASE"
if [ "$PARTE_D" = 1 ]; then
    git -C "$DATA" checkout -- scripts/sync_drive.sh   # igual a $DATA_LOCAL, que já está no ramo
    git -C "$DATA" merge --ff-only "$DATA_RELEASE"
    rm -f ~/.config/systemd/user/kanban-planning.service.d/raiz-so.conf ~/.config/systemd/user/kanban-raw-worker.service.d/raiz-so.conf
else
    echo "   Parte D adiada: a app só procura o Excel na raiz do Drive até ela entrar."
    for unit in kanban-planning kanban-raw-worker; do
        mkdir -p ~/.config/systemd/user/$unit.service.d
        printf '[Service]\nEnvironment=MES_RAW_WORKBOOK_FOLDERS=.\n' > ~/.config/systemd/user/$unit.service.d/raiz-so.conf
    done
fi
systemctl --user daemon-reload

echo "4/8 Conferir os hard links com o MES (nenhum muda nesta etapa)"
mapfile -t linked < <(find app/web/static -links +1 -type f | sort)
[ "${#linked[@]}" = "$HARD_LINKS" ] || { echo "   Depois do merge há ${#linked[@]} estáticos em hard link, não $HARD_LINKS. Pára."; exit 1; }
git diff --quiet HEAD -- "${linked[@]}" || { echo "   Os ficheiros ligados diferem do commit. Pára."; exit 1; }
echo "   ${#linked[@]} ficheiros, iguais ao commit"

if [ "$PARTE_D" = 1 ]; then
    echo "5/8 Carregar o Excel do Drive já (raiz e SAIDA/), fora das 08:15, para o recálculo ser um só"
    "$DATA/scripts/sync_drive.sh" || echo "   Aviso: o sync_drive.sh falhou (ver $DATA/drive_sync.log); a carga das 08:15 volta a tentar."
    tail -n 5 "$DATA/drive_sync.log" | sed 's/^/   /'
else
    echo "5/8 (Parte D adiada: sem carga à mão)"
fi

echo "6/8 Arrancar o worker e esperar pela geração nova (até $WAIT_MINUTES min)"
systemctl --user start kanban-raw-worker kanban-research-sync
ready=0
for i in $(seq 1 $((WAIT_MINUTES * 4))); do
    sleep 15
    if CONTRACT="$CONTRACT" .venv/bin/python - <<'PY'
import os
import scripts.audit_readonly as a
with a.planning_db() as c:
    jobs = a.query(c, "SELECT count(*) n FROM planning_mtg.raw_jobs WHERE status IN ('queued','running')")[0]["n"]
    capacity = a.query(c, """SELECT metadata->>'contract' contract FROM planning_mtg.raw_generations
                             WHERE dataset='capacity:perfis' ORDER BY id DESC LIMIT 1""")
    pending = a.query(c, """SELECT dataset FROM (SELECT DISTINCT ON (dataset) dataset, metadata FROM planning_mtg.raw_generations
                            WHERE dataset IN ('planning:perfis','planning:cantoneiras') ORDER BY dataset, id DESC) g
                            WHERE coalesce((metadata->>'aggregates_pending')::boolean, false)""")
done = not jobs and capacity and str(capacity[0]["contract"] or "").startswith(os.environ["CONTRACT"]) and not pending
raise SystemExit(0 if done else 1)
PY
    then ready=1; break; fi
    [ $((i % 4)) = 0 ] && echo "   $((i / 4)) min…"
done
[ "$ready" = 1 ] || echo "   Aviso: ao fim de $WAIT_MINUTES min a geração nova ainda não está completa; o web arranca na mesma e os números mudam quando acabar."

echo "7/8 Arrancar o web e o timer"
systemctl --user start kanban-planning
for i in $(seq 1 60); do
    curl -fsS -o /dev/null "$BASE_URL/planeamento/manual" 2>/dev/null && break
    sleep 1
done
for page in /planeamento/manual /planeamento/carteira /planeamento/setor/carga /planeamento/gantt /planeamento/setor/definicoes; do
    printf '   %-30s %s\n' "$page" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL$page")"
done
systemctl --user start planning-research-refresh.timer
systemctl --user is-active "${SERVICES[@]}" kanban-planning-tunnel planning-research-refresh.timer

echo "8/8 Conferir"
echo "   journalctl --user -u kanban-planning -u kanban-raw-worker -f   (procurar Traceback, ImportError, ValueError)"
echo "   Pedir para recarregar os separadores abertos: o JS antigo com o Python novo mostra «0 m», «0 kg» e «0 peças»"
echo "   onde o valor agora é desconhecido."
echo "   As propostas do Gantt técnico ficam desatualizadas por «motor» (contrato novo); o /planeamento/gantt não muda"
echo "   enquanto não houver cenário aceite."
