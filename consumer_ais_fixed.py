"""
Utility per il consumo dei messaggi AIS da Kafka in background.

Espone la classe `ConsumerAIS` che può essere avviata in un thread
e pubblica i messaggi su una `queue.Queue` passata dal chiamante.

Gli item messi in coda sono i dizionari già deserializzati (`msg.value`).

FIX: Sostituito consumer_timeout_ms + sleep loop con poll() continuo.
Questo elimina il gap di ~1s che causava scatti sulla living map
quando il flusso di messaggi rallentava (es. una nave finisce il percorso).
"""
import os
import json
import threading
import time
import traceback
from queue import Queue

from kafka import KafkaConsumer

# NOTE: bootstrap servers must be host:port (no http scheme)
BOOTSTRAP_SERVERS = "87.26.178.190:29092"
REAL_AIS_TOPIC = "ais_decoded.raw"
SIMULATION_AIS_TOPIC = "ais_decoded_simulation.raw"

class ConsumerAIS(threading.Thread):
    def __init__(self, out_queue: Queue, topic: str = REAL_AIS_TOPIC, bootstrap: str = None, group_id: str = None, is_simulation: bool = False):
        super().__init__(daemon=True)
        self.topic = topic
        self.out_queue = out_queue
        self.is_simulation = is_simulation
        self._stop = threading.Event()
        self.bootstrap = bootstrap or os.getenv("KAFKA_BOOTSTRAP", BOOTSTRAP_SERVERS)

        # Contatori diagnostici
        self._msg_count = 0
        self._drop_count = 0
        self._last_diag = time.time()

    def stop(self):
        self._stop.set()

    def _log_diagnostics(self):
        """Logga statistiche ogni 30 secondi."""
        now = time.time()
        if now - self._last_diag >= 30:
            print(f"[ConsumerAIS:{self.topic}] DIAG: received={self._msg_count} "
                  f"queue_size={self.out_queue.qsize()} "
                  f"drops={self._drop_count}", flush=True)
            self._msg_count = 0
            self._drop_count = 0
            self._last_diag = now

    def run(self):
        try:
            consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=self.bootstrap,
                key_deserializer=lambda k: k.decode("utf-8") if k else None,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")) if v else None,
                auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET", "latest"),
                # RIMOSSO consumer_timeout_ms: usava 1000ms che causava gap
                # nel flusso dati quando il rate di messaggi calava.
                # Ora usiamo poll() con timeout breve (200ms) che non esce
                # mai dal loop e mantiene il flusso costante.
            )
            print(f"[ConsumerAIS] Connected to Kafka at {self.bootstrap} for topic '{self.topic}'", flush=True)
        except Exception:
            print(f"[ConsumerAIS] Failed to connect to Kafka at {self.bootstrap} for topic '{self.topic}': {traceback.format_exc()}", flush=True)
            return

        try:
            while not self._stop.is_set():
                try:
                    # poll() con timeout 200ms: ritorna immediatamente se ci sono
                    # messaggi, altrimenti attende max 200ms. Non causa mai un gap
                    # di 1s come il vecchio consumer_timeout_ms + sleep pattern.
                    records = consumer.poll(timeout_ms=200, max_records=100)

                    for tp, messages in records.items():
                        for msg in messages:
                            if self._stop.is_set():
                                break
                            if msg is None:
                                continue

                            value = msg.value
                            if self.is_simulation:
                                value['is_simulation'] = True

                            self._msg_count += 1
                            try:
                                self.out_queue.put_nowait(value)
                            except Exception:
                                self._drop_count += 1

                    # Diagnostica periodica
                    self._log_diagnostics()

                except Exception:
                    time.sleep(1)
        finally:
            try:
                consumer.close()
            except Exception:
                pass


class ConsumerSimulation(ConsumerAIS):
    """Consumer specifico per il topic di simulazione AIS."""
    def __init__(self, out_queue: Queue, bootstrap: str = None, group_id: str = None):
        super().__init__(out_queue, topic=SIMULATION_AIS_TOPIC, bootstrap=bootstrap, group_id=group_id, is_simulation=True)


if __name__ == '__main__':
    # run standalone for debug: print incoming values
    import logging
    q = Queue()
    c = ConsumerAIS(q)
    c.start()
    try:
        while True:
            try:
                item = q.get(timeout=1)
                logging.info("Received AIS (standalone): %s", item)
            except Exception:
                pass
    except KeyboardInterrupt:
        c.stop()
        c.join()
