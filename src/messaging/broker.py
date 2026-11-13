from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.schemas.queue import QueueType

from src.core.config import settings

broker = RabbitBroker(settings.rabbitmq_url)

payments_queue = RabbitQueue(
    name="payments.new",
    durable=True,
    arguments={
        "x-queue-type": QueueType.QUORUM.value,
        "x-delivery-limit": 3,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": "payments.dlq",
    },
)

payments_dlq = RabbitQueue(
    name="payments.dlq",
    durable=True,
)
