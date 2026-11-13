from faststream.rabbit import RabbitBroker, RabbitQueue

from src.core.config import settings


broker = RabbitBroker(settings.rabbitmq_url)

payments_queue = RabbitQueue(
    name="payments.new",
    durable=True,
)
