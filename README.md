# Payment Processing Service

Асинхронный сервис обработки платежей на FastAPI, PostgreSQL и RabbitMQ.

## Архитектура

1. API принимает платеж и проверяет `X-API-Key`.
2. Платеж и outbox-событие сохраняются в одной транзакции PostgreSQL.
3. Publisher отправляет outbox-событие в очередь `payments.new`.
4. Consumer эмулирует обработку платежа:
   - 2–5 секунд;
   - 90% успешных обработок;
   - 10% неуспешных обработок.
5. Consumer обновляет статус и отправляет webhook.
6. После трёх ошибок доставки сообщение попадает в `payments.dlq`.

## Требования

- Docker;
- Docker Compose.

Локальная установка Python и PostgreSQL не требуется.

## Настройка

Создайте файл `.env` в корне проекта:

```env
DATABASE_URL=postgresql+asyncpg://payments:payments@localhost:5432/payments
RABBITMQ_URL=amqp://payments:payments@localhost:5672/
API_KEY=change-me
DB_ECHO=false
```

Для запуска через Compose значения подключения к PostgreSQL и RabbitMQ
настраиваются автоматически. `API_KEY` берётся из `.env`.

## Запуск

```bash
docker compose up --build
```

Compose автоматически:

- запустит PostgreSQL и RabbitMQ;
- применит миграции Alembic;
- запустит API;
- запустит outbox publisher;
- запустит payment consumer.

Проверка состояния:

```bash
docker compose ps
curl http://localhost:8000/health
```

Ожидаемый ответ healthcheck:

```json
{"status":"ok"}
```

Остановить сервисы:

```bash
docker compose down
```

Удалить контейнеры и тестовые данные PostgreSQL/RabbitMQ:

```bash
docker compose down -v
```

## API

### Создание платежа

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "Idempotency-Key: order-10001" \
  -d '{
    "amount": "1250.50",
    "currency": "RUB",
    "description": "Test payment",
    "metadata": {
      "order_id": "10001"
    },
    "webhook_url": "https://webhook.site/your-endpoint"
  }'
```

Ответ имеет статус `202 Accepted`:

```json
{
  "payment_id": "00000000-0000-0000-0000-000000000000",
  "status": "pending",
  "created_at": "2026-01-01T12:00:00Z"
}
```

Повторный запрос с тем же `Idempotency-Key` и теми же данными вернёт
существующий платеж. Использование ключа с другими данными вернёт `409 Conflict`.

### Получение платежа

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: change-me"
```

После обработки поле `status` станет `succeeded` или `failed`, а
`processed_at` будет заполнено.

## Webhook

После обработки платежа consumer отправляет `POST` на `webhook_url`:

```json
{
  "payment_id": "00000000-0000-0000-0000-000000000000",
  "status": "succeeded"
}
```

Webhook отправляется максимум три раза с экспоненциальной задержкой:
1 и 2 секунды между попытками. Ошибками считаются сетевые ошибки,
таймауты и HTTP-ответы `4xx/5xx`.

## RabbitMQ и DLQ

- Основная очередь: `payments.new`;
- Dead Letter Queue: `payments.dlq`;
- основная очередь использует quorum-тип;
- лимит неуспешных доставок сообщения — 3.

RabbitMQ Management UI доступен по адресу
<http://localhost:15672>.

Учётные данные по умолчанию:

```text
login: payments
password: payments
```

## Миграции

Миграции запускаются автоматически сервисом `migrate`.

Запустить вручную:

```bash
docker compose run --rm migrate alembic upgrade head
```

## Логи

```bash
docker compose logs -f api
docker compose logs -f publisher
docker compose logs -f consumer
```

## Структура проекта

```text
src/
├── api/                 # FastAPI routers и dependencies
├── core/                # настройки и подключение к БД
├── data/                # SQLAlchemy models и repositories
├── domain/              # schemas и payment service
└── messaging/           # RabbitMQ, publisher и consumer
alembic/                 # миграции базы данных
Dockerfile
docker-compose.yml
```
