import asyncio

class ReadOnlyQueue():
    
    def __init__(self, queue):
        self.queue = queue

    async def get(self):
        """
        Get the next item from queue, which has items in the format (priority, data)
        :return: next item from the queue
        """
        return (await self.queue.get())[1]

