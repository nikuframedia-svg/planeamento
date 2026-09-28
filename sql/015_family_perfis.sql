-- O schema mes_kanban é partilhado pelos setores MTG3 e MTG2.
-- Permite validar as folhas Serrote/Vanguard com family='perfis'.
BEGIN;

ALTER TABLE mes_kanban.validated_sheets
    DROP CONSTRAINT IF EXISTS validated_sheets_family_check;
ALTER TABLE mes_kanban.validated_sheets
    ADD CONSTRAINT validated_sheets_family_check
    CHECK (family IN ('chapa', 'cantoneiras', 'perfis'));

COMMIT;
