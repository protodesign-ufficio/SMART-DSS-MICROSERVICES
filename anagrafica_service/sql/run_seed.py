import psycopg2
import os
import json

COMPONENTS = [
    ("Prefiltro carburante + separatore condensa","Alimentazione carburante",500,"M1","fuel","Alimentazione carburante","serie","prefilter",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Filtro carburante fine","Alimentazione carburante",500,"M1","fuel","Alimentazione carburante","serie","fuel_filter",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Pompa alta pressione (common rail)","Alimentazione carburante",12000,"M6","fuel","Alimentazione carburante","serie","hp_pump",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Tubazioni AP + tubi di mandata","Alimentazione carburante",12000,"M6","fuel","Alimentazione carburante","serie","hp_lines",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Iniettori common rail (x12)","Alimentazione carburante",6000,"M5","fuel","Alimentazione carburante","serie","injectors",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Canne cilindro (x12)","Combustione + manovellismi",12000,"M6","combustion","Combustione + manovellismi","parallelo","cylinders",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Pistoni + segmenti (x12)","Combustione + manovellismi",12000,"M6","combustion","Combustione + manovellismi","parallelo","pistons",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Bielle (x12)","Combustione + manovellismi",12000,"M6","combustion","Combustione + manovellismi","parallelo","conrods",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Albero motore + cuscinetti","Combustione + manovellismi",12000,"M6","combustion","Combustione + manovellismi","parallelo","crankshaft",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Smorzatore di vibrazioni","Combustione + manovellismi",12000,"M6","combustion","Combustione + manovellismi","parallelo","damper",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Olio motore","Lubrificazione",500,"M1","lube","Lubrificazione","serie","engine_oil",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Filtro olio","Lubrificazione",500,"M1","lube","Lubrificazione","serie","oil_filter",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Pompe olio","Lubrificazione",12000,"M6","lube","Lubrificazione","serie","oil_pump",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Radiatore olio","Lubrificazione",12000,"M6","lube","Lubrificazione","serie","oil_radiator",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Iniettori olio (raffr. pist.)","Lubrificazione",12000,"M6","lube","Lubrificazione","serie","oil_injectors",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Impeller pompa acqua mare","Raffreddamento",500,"M1","cooling","Raffreddamento","mista","impeller",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Pompa liquido raffreddamento","Raffreddamento",6000,"M5","cooling","Raffreddamento","mista","lr_pump",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Termostati","Raffreddamento",6000,"M5","cooling","Raffreddamento","mista","thermostats",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Piastre scambiatore di calore","Raffreddamento",3000,"M4","cooling","Raffreddamento","mista","heat_exchanger",'{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000}}'),
    ("Intercooler","Raffreddamento",3000,"M4","cooling","Raffreddamento","mista","intercooler",'{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000}}'),
    ("Liquido raffreddamento","Raffreddamento",3000,"M4","cooling","Raffreddamento","mista","coolant",'{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000}}'),
    ("Tubi flessibili LR + acqua mare","Raffreddamento",3000,"M4","cooling","Raffreddamento","mista","coolant_hoses",'{"type":"rbd_man_d2862","m_level":"M4","intervals_h":{"LD":3200,"MD":3000,"HD":3000}}'),
    ("Filtro aria","Aspirazione + scarico",500,"M1","air","Aspirazione + scarico","serie","air_filter",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Turbocompressore","Aspirazione + scarico",6000,"M5","air","Aspirazione + scarico","serie","turbo",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Valvole + molle (x24 asp. + x24 scar.)","Distribuzione (valve train)",1000,"M2","dist","Distribuzione (valve train)","serie","valves",'{"type":"rbd_man_d2862","m_level":"M2","intervals_h":{"LD":800,"MD":1000,"HD":1200}}'),
    ("Bilancieri + punterie + albero a camme","Distribuzione (valve train)",12000,"M6","dist","Distribuzione (valve train)","serie","valve_train",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Cinghia trapezoidale dentata","Distribuzione (valve train)",6000,"M5","dist","Distribuzione (valve train)","serie","belt",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Tendicinghia + rulli di rinvio","Distribuzione (valve train)",6000,"M5","dist","Distribuzione (valve train)","serie","belt_tensioner",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
    ("Centralina EDC + memoria diagnosi","Ausiliari elettrici + diagnostica",500,"M1","aux","Ausiliari elettrici + diagnostica","parallelo","edc",'{"type":"rbd_man_d2862","m_level":"M1","intervals_h":{"LD":400,"MD":500,"HD":600}}'),
    ("Motorino di avviamento","Ausiliari elettrici + diagnostica",12000,"M6","aux","Ausiliari elettrici + diagnostica","parallelo","starter",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Alternatore trifase","Ausiliari elettrici + diagnostica",12000,"M6","aux","Ausiliari elettrici + diagnostica","parallelo","alternator",'{"type":"rbd_man_d2862","m_level":"M6","intervals_h":{"LD":12000,"MD":12000,"HD":18000}}'),
    ("Supporti elastici motore + cambio","Ausiliari elettrici + diagnostica",6000,"M5","aux","Ausiliari elettrici + diagnostica","parallelo","mounts",'{"type":"rbd_man_d2862","m_level":"M5","intervals_h":{"LD":null,"MD":6000,"HD":6000}}'),
]

conn = psycopg2.connect("dbname=anagrafica_db user=postgres password=admin host=host.docker.internal")
cur = conn.cursor()

# ALTER TABLE
print("Step 1: ALTER TABLE...")
cur.execute("""
ALTER TABLE componente
    ADD COLUMN IF NOT EXISTS rbd_level      TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_key  TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_name TEXT,
    ADD COLUMN IF NOT EXISTS rbd_chain_topo TEXT,
    ADD COLUMN IF NOT EXISTS component_key  TEXT
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_componente_rbd_chain ON componente (vascello_id, rbd_chain_key)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_componente_key ON componente (vascello_id, component_key)")

# Trova SIRIUS
cur.execute("SELECT id FROM vascello WHERE nome = 'SIRIUS' LIMIT 1")
sirius_row = cur.fetchone()
if not sirius_row:
    print("ERRORE: SIRIUS non trovata!")
    conn.rollback(); conn.close(); exit(1)
sirius_id = sirius_row[0]
print(f"Step 2: SIRIUS vascello_id = {sirius_id}")

# Insert componenti
inserted = 0
for nome, sotto, soglia, livello, chain_key, chain_name, topo, comp_key, modello in COMPONENTS:
    cur.execute("""
        INSERT INTO componente (id, vascello_id, nome_componente, sottosistema,
            ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json,
            rbd_level, rbd_chain_key, rbd_chain_name, rbd_chain_topo, component_key)
        VALUES (gen_random_uuid(), %s, %s, %s, 0.0, %s, %s::jsonb, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (sirius_id, nome, sotto, soglia, modello, livello, chain_key, chain_name, topo, comp_key))
    inserted += cur.rowcount

conn.commit()
print(f"Step 3: Inseriti {inserted} componenti RBD per SIRIUS")

# Verifica
cur.execute("SELECT count(*) FROM componente WHERE vascello_id = %s", (sirius_id,))
total = cur.fetchone()[0]
print(f"Totale componenti SIRIUS nel DB: {total}")
conn.close()
