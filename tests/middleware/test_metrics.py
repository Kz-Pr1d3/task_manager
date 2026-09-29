from fastapi import FastAPI
from starlette.testclient import TestClient

from src.middleware.metrics import MetricsMiddleware, REQUEST_COUNT


def test__metrics_middleware__uses_route_template():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/lists/{list_id}")
    async def get_list(list_id: int):
        return {"id": list_id}

    with TestClient(app=app) as client:
        response = client.get("/lists/42")

    assert response.status_code == 200

    samples = next(iter(REQUEST_COUNT.collect())).samples
    endpoints = {
        sample.labels["endpoint"]
        for sample in samples
        if sample.labels.get("method") == "GET" and sample.name.endswith("_total")
    }
    assert "/lists/{list_id}" in endpoints
    assert "/lists/42" not in endpoints
