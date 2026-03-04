from pydantic import BaseSettings

class Settings(BaseSettings):
    db_conn: str = "dbname=travelmar_db user=postgres password=admin host=localhost"
    ml_url: str = "http://localhost:8000/predict"
    opt_url: str = "http://192.168.1.250:8090/optimize"
    simulation_url: str = "http://192.168.1.224:5001/simulate"

settings = Settings()
