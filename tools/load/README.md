# Load testing

Ниже два сценария:

1. **Direct на receiver** (точные latency и delivery-метрики)
2. **Через Alertmanager без группировки** (проверка, что каждый алерт уходит отдельно)

## 1) Direct на receiver (рекомендуется для baseline)

Подними стенд:

```bash
docker compose up -d --build receiver mock-yandex
```

Запусти нагрузку:

```bash
python tools/load/receiver_load.py \
  --receiver-url http://localhost:8081/v1/alerts/chats/123 \
  --username user \
  --password pass \
  --rps 100 \
  --duration 60 \
  --mock-base http://localhost:18080
```

Скрипт печатает:

- `achieved_rps` — фактическая скорость
- `accepted_202` — сколько webhook принял receiver
- `delivered_to_mock` — сколько реально дошло до `sendText` (по Prometheus-метрике `mock_yandex_send_text_total`)
- `delivery_gap` — расхождение `accepted_202 - delivered_to_mock` (должно быть `0`)
- latency (`p50/p95/p99`, min/max/avg)

Если есть расхождения, смотри логи:

```bash
docker compose logs -f receiver mock-yandex
```

Также метрики доступны напрямую:

```bash
curl -s http://localhost:8081/metrics | rg receiver_
curl -s http://localhost:18080/metrics | rg mock_yandex_
```

## 2) Через Alertmanager, без группировки

Чтобы каждый алерт отправлялся отдельно, используй `alert-generator` в режиме `spray`:
он делает уникальный `alertname` на каждый алерт, поэтому при `group_by: ["alertname"]` Alertmanager не объединяет их.

```bash
docker compose up -d --build receiver mock-yandex alertmanager
docker compose --profile tools run --rm alert-generator \
  --mode spray \
  --count 1000 \
  --target chat \
  --group-key LoadNoGroup
```

Проверить, что доставки идут:

```bash
curl -s http://localhost:18080/_requests | python -m json.tool
```

Смотри поле `count` — оно должно расти на каждый отправленный алерт.

## Legacy: vegeta direct

Можно использовать и старый vegeta-сценарий:

```bash
cp tools/load/receiver_direct.json /tmp/payload.json
docker run --rm --network yandex-messanger-receiver_default \
  -v /tmp/payload.json:/payload.json:ro \
  -v "$(pwd)"/tools/load/targets_receiver_direct.txt:/targets.txt:ro \
  ghcr.io/tsenart/vegeta:latest attack -duration=10s -rate=50 -targets=/targets.txt | \
  ghcr.io/tsenart/vegeta:latest report
```

