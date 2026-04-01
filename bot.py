import asyncio
import os

from bot_manager import main


if __name__ == "__main__":
    try:
        if hasattr(asyncio, "WindowsSelectorEventLoopPolicy") and os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot runtime stopped.")
