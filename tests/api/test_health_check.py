

def test__health_check__success(client):
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
