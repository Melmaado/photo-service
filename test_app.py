from app import app

client = app.test_client()

def test_main_page():    
    response = client.get("/")
    assert response.status_code == 200
    assert "Le nom de la machine est:" in response.text

def test_health():
    response_health = client.get("/health")
    assert response_health.status_code == 200
    assert response_health.get_json() == {'status':'ok'}

def test_metrics():
    response_metrics = client.get("/metrics")
    assert response_metrics.status_code == 200
    assert "flask_http_request_total" in response_metrics.text