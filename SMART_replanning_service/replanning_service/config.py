"""
Configurazione del servizio di replanning.
"""
import os


def _int_env(name: str, default: int) -> int:
	return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
	return float(os.getenv(name, str(default)))

# Porta del servizio
SERVICE_PORT = int(os.getenv("REPLANNING_SERVICE_PORT", "8001"))

# Host del servizio
SERVICE_HOST = os.getenv("REPLANNING_SERVICE_HOST", "0.0.0.0")

# Configurazione Kafka
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_REPLANNING_TOPIC", "vessel-positions")
KAFKA_TOPIC_ANALYTICS = os.getenv("KAFKA_ANALYTICS_TOPIC", "analytics_ais.raw")
KAFKA_TOPIC_NOTIFICATIONS = os.getenv("KAFKA_TOPIC_NOTIFICATIONS", "notifications")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "replanning-service-group")

# Parametri trigger replanning
REPLANNING_THETA_MIN = _float_env("REPLANNING_THETA_MIN", 10.0)
REPLANNING_THETA_CRITICAL_MIN = _float_env("REPLANNING_THETA_CRITICAL_MIN", 30.0)
REPLANNING_MAX_LATE = _int_env("REPLANNING_MAX_LATE", 2)
REPLANNING_MAX_CRITICAL = _int_env("REPLANNING_MAX_CRITICAL", 1)
REPLANNING_TOTAL_DELAY_MAX = _float_env("REPLANNING_TOTAL_DELAY_MAX", 60.0)
REPLANNING_SINGLE_DELAY_MAX = _float_env("REPLANNING_SINGLE_DELAY_MAX", 40.0)
REPLANNING_HORIZON_MINUTES = _int_env("REPLANNING_HORIZON_MINUTES", 120)

# Stabilità operativa
REPLANNING_COOLDOWN_MINUTES = _int_env("REPLANNING_COOLDOWN_MINUTES", 30)
REPLANNING_FREEZE_WINDOW_MINUTES = _int_env("REPLANNING_FREEZE_WINDOW_MINUTES", 15)
