#!/usr/bin/env python3
"""Cron job: Deliver due Ghost Threads."""
import asyncio
import sys
sys.path.insert(0, ".")

from brain.ghost_thread_socket import process_due_ghosts

async def main():
    delivered = await process_due_ghosts(batch_size=20)
    print(f"Delivered {len(delivered)} ghost threads")

if __name__ == "__main__":
    asyncio.run(main())
