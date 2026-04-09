# Load testing (vegeta)

## Direct нагрузка на receiver

Внутри docker-сети compose удобнее использовать имя сервиса `receiver`.

1) Подготовить payload:

```bash
cp tools/load/receiver_direct.json /tmp/payload.json
```

2) Запустить vegeta:

```bash
docker run --rm --network yandex-messanger-receiver_default \
  -v /tmp/payload.json:/payload.json:ro \
  -v "$(pwd)"/tools/load/targets_receiver_direct.txt:/targets.txt:ro \
  ghcr.io/tsenart/vegeta:latest attack -duration=10s -rate=50 -targets=/targets.txt | \
  ghcr.io/tsenart/vegeta:latest report
```

> Примечание: название docker-сети (`..._default`) зависит от папки/проекта. Его можно посмотреть командой `docker network ls`.

