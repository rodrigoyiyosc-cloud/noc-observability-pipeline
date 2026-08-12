from fastapi import FastAPI, Request
from datetime import datetime, timezone
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("webhook_service")

app = FastAPI(title="NOC Webhook Service")


@app.post("/alert")
async def receive_alert(request: Request):
    payload = await request.json()

    logger.info(
        "ALERT RECEIVED at %s\n%s",
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, indent=2, ensure_ascii=False),
    )

    # TODO Fase 4: enrutar hacia Jira/ServiceNow o pipeline de ML aquí

    return {"status": "received"}


@app.get("/health")
async def health():
    return {"status": "ok"}