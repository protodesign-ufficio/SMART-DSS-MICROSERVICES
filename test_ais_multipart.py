"""
Test diagnostico per il problema delle imbarcazioni non visibili.

PROBLEMA TROVATO:
  I messaggi AIS Type 5 (Static & Voyage) sono multipart (2 frammenti NMEA).
  Il simulatore invia ogni frammento come messaggio Kafka SEPARATO.
  
  bridge-components riceve UN singolo frammento per volta e tenta di decodificarlo
  con pyais.decode(), che richiede TUTTI i frammenti insieme.
  
  Risultato: MissingMultipartMessageException: Missing fragment numbers: [1]

  Questo errore causa il fallimento della decodifica dei Type 5, che sono quelli
  che trasportano nome nave, destinazione, ETA - dati essenziali per la visualizzazione.
  Senza Type 5 decodificati correttamente, il frontend non ha i metadati delle navi.

  I Type 1 (Position Report) sono single-part e funzionano correttamente.
"""

import sys
import os

# Aggiungi simulator_service al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "simulator_service"))

from pyais import decode as ais_decode


def test_type1_single_fragment():
    """Type 1 (Position Report) è single-fragment: decode funziona."""
    from ais_generator import PositionReportParams, generate_position_report

    params = PositionReportParams(
        mmsi=247360500,
        latitude=40.65,
        longitude=14.55,
        speed=12.5,
        course=180,
        heading=180,
        timestamp=30,
    )
    fragments = generate_position_report(params)
    print(f"\n=== Test Type 1 (Position Report) ===")
    print(f"Frammenti generati: {len(fragments)}")
    for f in fragments:
        print(f"  {f}")

    # Simula quello che fa bridge-components: decodifica UN messaggio alla volta
    # Per Type 1 questo funziona perché è single-fragment
    try:
        decoded = ais_decode(*fragments)
        msg = decoded.asdict()
        print(f"  ✓ Decodifica OK - MMSI={msg['mmsi']}, lat={msg['lat']}, lon={msg['lon']}")
        return True
    except Exception as e:
        print(f"  ✗ Decodifica FALLITA: {e}")
        return False


def test_type5_fragments_sent_separately():
    """
    Type 5 (Static Voyage) è multipart (2 frammenti).
    Simula il BUG ATTUALE: ogni frammento inviato come messaggio Kafka separato.
    bridge-components riceve UN frammento e tenta decode → FALLISCE.
    """
    from ais_generator import StaticVoyageParams, generate_static_voyage_report

    params = StaticVoyageParams(
        mmsi=247360500,
        callsign="TESTNAV",
        name="TEST NAVE",
        ship_type=70,
        to_bow=50,
        to_stern=20,
        to_port=10,
        to_starboard=10,
        eta_month=3,
        eta_day=26,
        eta_hour=18,
        eta_minute=30,
        draft=5.0,
        destination="SALERNO",
    )
    fragments = generate_static_voyage_report(params)

    print(f"\n=== Test Type 5 (Static Voyage) - BUG: frammenti separati ===")
    print(f"Frammenti generati: {len(fragments)}")
    for f in fragments:
        print(f"  {f}")

    # Simula bridge-components: riceve ogni frammento come messaggio Kafka separato
    errors = 0
    for i, frag in enumerate(fragments):
        try:
            decoded = ais_decode(frag)
            msg = decoded.asdict()
            print(f"  Frammento {i+1}: ✓ Decode OK (improbabile per multipart)")
        except Exception as e:
            print(f"  Frammento {i+1}: ✗ {type(e).__name__}: {e}")
            errors += 1

    if errors > 0:
        print(f"\n  >>> QUESTO È IL BUG! {errors}/{len(fragments)} frammenti falliscono")
        print(f"  >>> bridge-components riceve i frammenti separatamente e non può decodificarli")
    return errors > 0  # True = bug riprodotto


def test_type5_fragments_sent_together():
    """
    FIX PROPOSTO: inviare tutti i frammenti come singolo messaggio Kafka
    (separati da newline). bridge-components li decodifica tutti insieme.
    """
    from ais_generator import StaticVoyageParams, generate_static_voyage_report

    params = StaticVoyageParams(
        mmsi=247360500,
        callsign="TESTNAV",
        name="TEST NAVE",
        ship_type=70,
        to_bow=50,
        to_stern=20,
        to_port=10,
        to_starboard=10,
        eta_month=3,
        eta_day=26,
        eta_hour=18,
        eta_minute=30,
        draft=5.0,
        destination="SALERNO",
    )
    fragments = generate_static_voyage_report(params)

    print(f"\n=== Test Type 5 (Static Voyage) - FIX: frammenti concatenati ===")

    # FIX: Invia tutti i frammenti come singolo messaggio
    try:
        decoded = ais_decode(*fragments)
        msg = decoded.asdict()
        print(f"  ✓ Decode OK - MMSI={msg['mmsi']}, name={msg.get('shipname','?')}, dest={msg.get('destination','?')}")
        return True
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
        return False


def test_concatenated_kafka_message():
    """
    Simula il fix: i frammenti vengono concatenati con newline prima dell'invio
    a Telegraf/Kafka. Il consumer li splitta e decodifica insieme.
    """
    from ais_generator import StaticVoyageParams, generate_static_voyage_report

    params = StaticVoyageParams(
        mmsi=247360500,
        callsign="TESTNAV",
        name="TEST NAVE",
        ship_type=70,
        to_bow=50,
        to_stern=20,
        to_port=10,
        to_starboard=10,
        eta_month=3,
        eta_day=26,
        eta_hour=18,
        eta_minute=30,
        draft=5.0,
        destination="SALERNO",
    )
    fragments = generate_static_voyage_report(params)

    # Simula invio concatenato come un singolo valore Kafka
    concatenated = "\n".join(fragments)
    print(f"\n=== Test messaggio Kafka concatenato ===")
    print(f"  Payload Kafka: {repr(concatenated[:80])}...")

    # Simula consumer: splitta e decodifica
    received_parts = concatenated.strip().split("\n")
    try:
        decoded = ais_decode(*received_parts)
        msg = decoded.asdict()
        print(f"  ✓ Consumer decode OK - MMSI={msg['mmsi']}, name={msg.get('shipname','?')}")
        return True
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("DIAGNOSTICA: Problema imbarcazioni non visibili in simulazione")
    print("=" * 70)

    r1 = test_type1_single_fragment()
    r2 = test_type5_fragments_sent_separately()
    r3 = test_type5_fragments_sent_together()
    r4 = test_concatenated_kafka_message()

    print("\n" + "=" * 70)
    print("RISULTATI:")
    print(f"  Type 1 single-fragment decode:      {'✓ OK' if r1 else '✗ FAIL'}")
    print(f"  Type 5 BUG riprodotto:              {'✓ Confermato' if r2 else '✗ Non riprodotto'}")
    print(f"  Type 5 fix (decode insieme):        {'✓ OK' if r3 else '✗ FAIL'}")
    print(f"  Type 5 fix (kafka concatenato):     {'✓ OK' if r4 else '✗ FAIL'}")
    print("=" * 70)

    if r2 and r3:
        print("\nDIAGNOSI CONFERMATA:")
        print("  Il simulatore invia ogni frammento AIS Type 5 come messaggio Kafka")
        print("  separato. bridge-components riceve un frammento alla volta e fallisce")
        print("  la decodifica con MissingMultipartMessageException.")
        print("\nSOLUZIONE:")
        print("  Concatenare i frammenti multipart in un singolo messaggio Kafka.")
        print("  In ais_generator.py, modificare _do_send per gestire messaggi multipart")
        print("  OPPURE in vessel.py, inviare tutti i frammenti Type 5 come unico blocco.")
