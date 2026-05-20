-- =============================================================================
-- MIGRAZIONE + SEED: RBD Componenti nave SIRIUS
-- Motore: MAN D2862 / D2868 LE4XX
-- =============================================================================
-- Eseguire su: anagrafica_db
-- Idempotente: si (usa ON CONFLICT DO NOTHING e ADD COLUMN IF NOT EXISTS)
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. ESTENSIONE TABELLA componente con campi RBD
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE componente
    ADD COLUMN IF NOT EXISTS rbd_level        TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_key    TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_name   TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_topo   TEXT,
    ADD COLUMN IF NOT EXISTS component_key    TEXT;

-- Indice per ricerche per catena RBD
CREATE INDEX IF NOT EXISTS idx_componente_rbd_chain
    ON componente (vascello_id, rbd_chain_key);

CREATE INDEX IF NOT EXISTS idx_componente_key
    ON componente (vascello_id, component_key);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. INSERIMENTO NAVE SIRIUS
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO vascello (
    id,
    mmsi,
    nome,
    capacita_passeggeri,
    costo_orario_esercizio,
    velocita_max_nodi,
    stato_salute_aggregato,
    profilo_consumo_json,
    data_creazione
)
SELECT
    gen_random_uuid(),
    '247320800',
    'SIRIUS',
    120,
    380.00,
    22.0,
    85.0,
    '{"10": 38, "15": 65, "18": 95, "22": 148}'::jsonb,
    now()
WHERE NOT EXISTS (SELECT 1 FROM vascello WHERE nome = 'SIRIUS');

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. SEED COMPONENTI RBD — usa CTE per risolvere il vascello_id di SIRIUS
-- ─────────────────────────────────────────────────────────────────────────────
-- Intervalli di manutenzione (ore) per modalità:
--   LD: M1=400  M2=800   M3=1600  M4=3200  M5=null   M6=12000
--   MD: M1=500  M2=1000  M3=2000  M4=3000  M5=6000   M6=12000  (DEFAULT)
--   HD: M1=600  M2=1200  M3=2400  M4=3000  M5=6000   M6=18000
--
-- soglia_manutenzione = intervallo MD (modalità operativa di default)
-- modello_guasto_json = intervalli completi per LD/MD/HD + metadati RBD
-- ─────────────────────────────────────────────────────────────────────────────

WITH sirius AS (
    SELECT id AS vascello_id FROM vascello WHERE nome = 'SIRIUS' LIMIT 1
)

INSERT INTO componente (
    id,
    vascello_id,
    nome_componente,
    sottosistema,
    ore_utilizzo_totali,
    soglia_manutenzione,
    modello_guasto_json,
    rbd_level,
    rbd_chain_key,
    rbd_chain_name,
    rbd_chain_topo,
    component_key
)
SELECT
    gen_random_uuid(),
    sirius.vascello_id,
    c.nome_componente,
    c.sottosistema,
    0.0,
    c.soglia_md,
    c.modello_guasto_json::jsonb,
    c.rbd_level,
    c.rbd_chain_key,
    c.rbd_chain_name,
    c.rbd_chain_topo,
    c.component_key
FROM sirius, (VALUES

    -- ── Alimentazione carburante (serie) ─────────────────────────────────────
    (
        'Prefiltro carburante + separatore condensa',
        'Alimentazione carburante',
        500, 'M1', 'fuel', 'Alimentazione carburante', 'serie', 'prefilter',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Cambio prefiltro e separatore condensa. Controllo visivo tubazioni."}'
    ),
    (
        'Filtro carburante fine',
        'Alimentazione carburante',
        500, 'M1', 'fuel', 'Alimentazione carburante', 'serie', 'fuel_filter',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Sostituzione filtro carburante fine. Spurgo acqua."}'
    ),
    (
        'Pompa alta pressione (common rail)',
        'Alimentazione carburante',
        12000, 'M6', 'fuel', 'Alimentazione carburante', 'serie', 'hp_pump',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione pompa AP in revisione generale TBO."}'
    ),
    (
        'Tubazioni AP + tubi di mandata',
        'Alimentazione carburante',
        12000, 'M6', 'fuel', 'Alimentazione carburante', 'serie', 'hp_lines',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione tubi alta pressione e tubi di ritorno carburante."}'
    ),
    (
        'Iniettori common rail (×12)',
        'Alimentazione carburante',
        6000, 'M5', 'fuel', 'Alimentazione carburante', 'serie', 'injectors',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva iniettori common rail su tutti e 12 i cilindri."}'
    ),

    -- ── Combustione + manovellismi (parallelo) ───────────────────────────────
    (
        'Canne cilindro (×12)',
        'Combustione + manovellismi',
        12000, 'M6', 'combustion', 'Combustione + manovellismi', 'parallelo', 'cylinders',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione canne cilindro in revisione generale TBO."}'
    ),
    (
        'Pistoni + segmenti (×12)',
        'Combustione + manovellismi',
        12000, 'M6', 'combustion', 'Combustione + manovellismi', 'parallelo', 'pistons',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione pistoni e fasce elastiche in revisione generale."}'
    ),
    (
        'Bielle (×12)',
        'Combustione + manovellismi',
        12000, 'M6', 'combustion', 'Combustione + manovellismi', 'parallelo', 'conrods',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione bielle e cuscinetti di biella."}'
    ),
    (
        'Albero motore + cuscinetti',
        'Combustione + manovellismi',
        12000, 'M6', 'combustion', 'Combustione + manovellismi', 'parallelo', 'crankshaft',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Rettifica o sostituzione albero motore e cuscinetti di banco."}'
    ),
    (
        'Smorzatore di vibrazioni',
        'Combustione + manovellismi',
        12000, 'M6', 'combustion', 'Combustione + manovellismi', 'parallelo', 'damper',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione smorzatore torsionale a viscosi."}'
    ),

    -- ── Lubrificazione (serie) ───────────────────────────────────────────────
    (
        'Olio motore',
        'Lubrificazione',
        500, 'M1', 'lube', 'Lubrificazione', 'serie', 'engine_oil',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Sostituzione olio motore MAN. Controllo livello e analisi visiva colore."}'
    ),
    (
        'Filtro olio',
        'Lubrificazione',
        500, 'M1', 'lube', 'Lubrificazione', 'serie', 'oil_filter',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Sostituzione filtro olio motore."}'
    ),
    (
        'Pompe olio',
        'Lubrificazione',
        12000, 'M6', 'lube', 'Lubrificazione', 'serie', 'oil_pump',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione pompe olio principale e ausiliaria in revisione TBO."}'
    ),
    (
        'Radiatore olio',
        'Lubrificazione',
        12000, 'M6', 'lube', 'Lubrificazione', 'serie', 'oil_radiator',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione radiatore olio (scambiatore olio/acqua)."}'
    ),
    (
        'Iniettori olio (raffr. pist.)',
        'Lubrificazione',
        12000, 'M6', 'lube', 'Lubrificazione', 'serie', 'oil_injectors',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione ugelli raffreddamento pistone."}'
    ),

    -- ── Raffreddamento (mista) ───────────────────────────────────────────────
    (
        'Impeller pompa acqua mare',
        'Raffreddamento',
        500, 'M1', 'cooling', 'Raffreddamento', 'mista', 'impeller',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Sostituzione girante in gomma pompa acqua di mare."}'
    ),
    (
        'Pompa liquido raffreddamento',
        'Raffreddamento',
        6000, 'M5', 'cooling', 'Raffreddamento', 'mista', 'lr_pump',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva pompa LR (acqua dolce)."}'
    ),
    (
        'Termostati',
        'Raffreddamento',
        6000, 'M5', 'cooling', 'Raffreddamento', 'mista', 'thermostats',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva termostati circuito LR."}'
    ),
    (
        'Piastre scambiatore di calore',
        'Raffreddamento',
        3000, 'M4', 'cooling', 'Raffreddamento', 'mista', 'heat_exchanger',
        '{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000},"max_anni":4,"note":"Pulizia e controllo piastre scambiatore acqua mare/acqua dolce. Depositi sale."}'
    ),
    (
        'Intercooler',
        'Raffreddamento',
        3000, 'M4', 'cooling', 'Raffreddamento', 'mista', 'intercooler',
        '{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000},"max_anni":4,"note":"Pulizia intercooler. Controllo depositi salini e perdite."}'
    ),
    (
        'Liquido raffreddamento',
        'Raffreddamento',
        3000, 'M4', 'cooling', 'Raffreddamento', 'mista', 'coolant',
        '{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000},"max_anni":4,"note":"Sostituzione liquido raffreddamento. Controllo pH e protezione antigelo."}'
    ),
    (
        'Tubi flessibili LR + acqua mare',
        'Raffreddamento',
        3000, 'M4', 'cooling', 'Raffreddamento', 'mista', 'coolant_hoses',
        '{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000},"max_anni":4,"note":"Sostituzione tubi flessibili circuito acqua dolce e acqua mare."}'
    ),

    -- ── Aspirazione + scarico (serie) ────────────────────────────────────────
    (
        'Filtro dell''aria',
        'Aspirazione + scarico',
        500, 'M1', 'air', 'Aspirazione + scarico', 'serie', 'air_filter',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Sostituzione o pulizia elemento filtrante aria. Controllo collettore aspirazione."}'
    ),
    (
        'Turbocompressore',
        'Aspirazione + scarico',
        6000, 'M5', 'air', 'Aspirazione + scarico', 'serie', 'turbo',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva turbocompressore. Controllo gioco assiale."}'
    ),

    -- ── Distribuzione (valve train) (serie) ──────────────────────────────────
    (
        'Valvole + molle (×24 asp. + ×24 scar.)',
        'Distribuzione (valve train)',
        1000, 'M2', 'dist', 'Distribuzione (valve train)', 'serie', 'valves',
        '{"type":"rbd_man_d2862","m_level":"M2","intervals_h":{"LD":800,"MD":1000,"HD":1200},"max_anni":1,"note":"Controllo e regolazione gioco valvole aspirazione (0.25mm) e scarico (0.35mm) a freddo."}'
    ),
    (
        'Bilancieri + punterie + albero a camme',
        'Distribuzione (valve train)',
        12000, 'M6', 'dist', 'Distribuzione (valve train)', 'serie', 'valve_train',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione bilancieri, punterie idrauliche e albero a camme in TBO."}'
    ),
    (
        'Cinghia trapezoidale dentata',
        'Distribuzione (valve train)',
        6000, 'M5', 'dist', 'Distribuzione (valve train)', 'serie', 'belt',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva cinghia dentata distribuzione."}'
    ),
    (
        'Tendicinghia + rulli di rinvio',
        'Distribuzione (valve train)',
        6000, 'M5', 'dist', 'Distribuzione (valve train)', 'serie', 'belt_tensioner',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione tendicinghia automatico e rulli di rinvio contestuale alla cinghia."}'
    ),

    -- ── Ausiliari elettrici + diagnostica (parallelo) ─────────────────────────
    (
        'Centralina EDC + memoria diagnosi',
        'Ausiliari elettrici + diagnostica',
        500, 'M1', 'aux', 'Ausiliari elettrici + diagnostica', 'parallelo', 'edc',
        '{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600},"max_anni":1,"note":"Lettura e cancellazione codici guasto con MAN-cats®. Aggiornamento firmware EDC."}'
    ),
    (
        'Motorino di avviamento',
        'Ausiliari elettrici + diagnostica',
        12000, 'M6', 'aux', 'Ausiliari elettrici + diagnostica', 'parallelo', 'starter',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione motorino avviamento in revisione generale."}'
    ),
    (
        'Alternatore trifase',
        'Ausiliari elettrici + diagnostica',
        12000, 'M6', 'aux', 'Ausiliari elettrici + diagnostica', 'parallelo', 'alternator',
        '{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000},"note":"Sostituzione alternatore trifase e regolatore di tensione."}'
    ),
    (
        'Supporti elastici motore + cambio',
        'Ausiliari elettrici + diagnostica',
        6000, 'M5', 'aux', 'Ausiliari elettrici + diagnostica', 'parallelo', 'mounts',
        '{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000},"note":"Sostituzione preventiva supporti antivibranti motore e cambio."}'
    )

) AS c(
    nome_componente, sottosistema,
    soglia_md, rbd_level, rbd_chain_key, rbd_chain_name, rbd_chain_topo, component_key,
    modello_guasto_json
)
ON CONFLICT DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. VERIFICA
-- ─────────────────────────────────────────────────────────────────────────────
-- Eseguire dopo il seed per verificare il risultato:
--
--   SELECT rbd_chain_name, rbd_chain_topo, count(*) AS n_componenti
--   FROM componente c
--   JOIN vascello v ON v.id = c.vascello_id
--   WHERE v.nome = 'SIRIUS'
--   GROUP BY rbd_chain_name, rbd_chain_topo
--   ORDER BY rbd_chain_name;
--
-- Atteso: 7 catene, 32 componenti totali.
-- ─────────────────────────────────────────────────────────────────────────────
