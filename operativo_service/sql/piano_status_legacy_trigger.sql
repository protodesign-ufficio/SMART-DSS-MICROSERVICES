CREATE OR REPLACE FUNCTION public.fn_ricalcola_stato_piano(p_piano_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_stato_corrente public.piano_operativo_stato;
    v_has_plan_or_running boolean;
    v_tot_corse integer;
    v_corse_coperte integer;
    v_new_stato public.piano_operativo_stato;
BEGIN
    SELECT stato INTO v_stato_corrente
    FROM piano_operativo
    WHERE id = p_piano_id;

    IF v_stato_corrente = 'ARCHIVIATO' THEN
        RETURN;
    END IF;

    IF v_stato_corrente = 'ATTIVO' THEN
        RETURN;
    END IF;

    IF v_stato_corrente = 'VALIDATO' THEN
        RETURN;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM assegnazione
        WHERE piano_id = p_piano_id
          AND stato_esecuzione IN ('PIANIFICATA','IN_CORSO')
    ) INTO v_has_plan_or_running;

    IF NOT v_has_plan_or_running THEN
        v_new_stato := 'CREATO';
    ELSE
                IF to_regclass('public.percorso') IS NOT NULL THEN
                        EXECUTE $q$
                                SELECT COUNT(DISTINCT c.id)
                                FROM piano_operativo po
                                JOIN corsa c
                                    ON DATE(c.orario_partenza_schedulato) = DATE(po.data_riferimento)
                                WHERE po.id = $1
                        $q$
                        INTO v_tot_corse
                        USING p_piano_id;

                        EXECUTE $q$
                                SELECT COUNT(DISTINCT c.id)
                                FROM piano_operativo po
                                JOIN corsa c
                                    ON DATE(c.orario_partenza_schedulato) = DATE(po.data_riferimento)
                                JOIN percorso p ON p.id_corsa = c.id
                                JOIN assegnazione a ON a.percorso_id = p.id
                                WHERE po.id = $1
                                    AND a.piano_id = $1
                                    AND a.stato_esecuzione IN ('PIANIFICATA','IN_CORSO')
                        $q$
                        INTO v_corse_coperte
                        USING p_piano_id;
                ELSE
                        SELECT COUNT(DISTINCT c.id)
                        INTO v_tot_corse
                        FROM piano_operativo po
                        JOIN corsa c
                            ON DATE(c.orario_partenza_schedulato) = DATE(po.data_riferimento)
                        WHERE po.id = p_piano_id;

                        SELECT COUNT(DISTINCT a.percorso_id)
                        INTO v_corse_coperte
                        FROM assegnazione a
                        WHERE a.piano_id = p_piano_id
                            AND a.stato_esecuzione IN ('PIANIFICATA','IN_CORSO');
                END IF;

        IF v_corse_coperte = v_tot_corse AND v_tot_corse > 0 THEN
            v_new_stato := 'PRONTO';
        ELSE
            v_new_stato := 'IN_OTTIMIZZAZIONE';
        END IF;
    END IF;

    UPDATE piano_operativo
    SET stato = v_new_stato
    WHERE id = p_piano_id
      AND stato IS DISTINCT FROM v_new_stato;
END;
$$;

CREATE OR REPLACE FUNCTION public.trg_assegnazione_aggiorna_piano()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM public.fn_ricalcola_stato_piano(OLD.piano_id);
    ELSE
        PERFORM public.fn_ricalcola_stato_piano(NEW.piano_id);
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_promote_piano_to_pronto_on_assignment ON assegnazione;
DROP FUNCTION IF EXISTS trg_promote_piano_to_pronto_on_assignment();
DROP TRIGGER IF EXISTS trg_assegnazione_aiud ON assegnazione;

CREATE TRIGGER trg_assegnazione_aiud
AFTER INSERT OR UPDATE OR DELETE
ON assegnazione
FOR EACH ROW
EXECUTE FUNCTION public.trg_assegnazione_aggiorna_piano();

CREATE INDEX IF NOT EXISTS idx_assegnazione_piano_stato
ON assegnazione (piano_id, stato_esecuzione);

CREATE INDEX IF NOT EXISTS idx_assegnazione_percorso
ON assegnazione (percorso_id);

DO $$
BEGIN
    IF to_regclass('public.percorso') IS NOT NULL THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_percorso_corsa ON percorso (id_corsa)';
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_corsa_data
ON corsa (DATE(orario_partenza_schedulato));
